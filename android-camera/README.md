# Lab Log Android Camera（手机采集视频并推流）

这是一个将 Android 手机当作“网络相机”的小项目：  
手机端使用 CameraX + MediaCodec 采集并编码 H.264 视频，通过 WebSocket 推送到 Python 服务器；  
服务器按会话把裸流落盘，并在录制结束时用 `ffmpeg` 封装成 MP4 文件。

---

## 整体架构概览

- **Android 端（本目录 `android-camera/`）**
  - Kotlin + Jetpack Compose UI
  - CameraX 负责相机预览 + YUV 图像采集
  - MediaCodec 负责 H.264 硬件编码
  - OkHttp WebSocket 负责与服务器通信
- **后端（`backend/server.py`）**
  - 使用 `websockets` 库实现 WebSocket 服务器
  - 接收来自手机的 H.264 帧，写入 `recordings/<client>/<session>/stream.h264`
  - 根据时间戳估算 FPS，使用 `ffmpeg` 封装为 MP4

数据流大致如下：

1. App 启动并获取相机权限后，会立即初始化临时 ImageAnalysis 采集一帧以获取实际分辨率（根据当前选择的摄像头），并在连接后端时通过能力上报发送该信息；
2. 服务器从终端输入 `start [WIDTH:HEIGHT] [BITRATE_MB] [FPS]`（例如 `start 4:3 4 10` 或 `start 1:1 4 10` 或 `start`），向所有客户端广播 `start_capture` 命令；
3. App 收到命令后：
   - 如果命令中包含 `aspectRatio`，更新 UI 中的宽高比选择并用于录制；否则使用当前 UI 中选择的宽高比（4:3、16:9 或不裁剪）；
   - 记录服务端要求的目标宽高比 / 码率（MB） / FPS；
   - 根据当前选择的摄像头（后置/前置）创建 ImageAnalysis 和 Preview；
   - 相机预览嵌入在主界面顶部的**正方形区域**中，预览区域宽高比自动匹配选择的宽高比（4:3、16:9 或不裁剪时显示为正方形）；
   - 使用 CameraX **ViewPort + UseCaseGroup** 确保预览（Preview）和采集（ImageAnalysis）的 FOV 完全一致，用户在预览中看到的画面就是发送到服务器的画面；
   - 在 `ImageAnalysis` 分析流中按需丢帧，并根据选择的宽高比进行安全尺寸裁剪（4:3/16:9 时裁剪，不裁剪时使用全帧但做 32 对齐），然后将图像编码为 H.264；
   - 根据设备物理方向和摄像头类型计算正确的 rotation 值（前置摄像头在竖放/倒放时需要额外旋转 180 度）；
   - 通过 WebSocket 以"带自定义二进制帧头的 H.264 帧"发送给服务器；
4. 服务器端：
   - 收到 `capture_started` 状态时打开一个录制会话（包含正确的 rotation 值）；
   - 按帧解出时间戳和裸 H.264 数据写文件；
   - 收到 `capture_stopped` 或连接断开时结束会话，根据 rotation 值使用 `ffmpeg` 旋转视频并封装成 MP4，同时提取第一帧保存为缩略图。

---

## Android 模块结构（`app/`）

- `app/src/main/java/com/example/lablogcamera/MainActivity.kt`
  - **数据类与协议**
    - `ServerCommand`：服务端下发的命令抽象（如 `"start_capture"`/`"stop_capture"`）。
    - `CommandPayload`：`start_capture` 的参数（编码格式、分辨率、码率、fps）。
    - `ClientStatus`：App 上报给服务器的状态（`ready`、`capture_started` 等）。
    - `EncodedFrame`：编码后的 H.264 帧及设备时间戳（毫秒）。
    - `ClientCapabilities` / `ResolutionOption`：设备支持的相机分辨率能力。
  - **编码器封装 `H264Encoder`**
    - 使用 `MediaCodec` 以 `COLOR_FormatYUV420SemiPlanar`（NV12）输出 H.264。
    - `start(width, height, bitrate, targetFps)`：配置编码器；`targetFps<=0` 时使用默认 10fps 作为编码参考。
    - `encode(image: ImageProxy, cropRect: Rect)`：
      - 调用扩展函数 `ImageProxy.toNv12ByteArray(cropRect)` 将 YUV_420_888 转为 NV12；
      - 送入编码器，循环读取输出缓冲区；
      - 将编码好的字节及时间戳通过回调传出。
    - `stop()`：安全停止并释放编码器。
  - **`WebSocketViewModel`（核心控制中枢）**
    - 维护 UI 状态 `WebSocketUiState`：URL、连接状态、是否在推流、状态文本。
    - WebSocket 生命周期：
      - `connect()`：建立到 `ws://host:port/android-cam` 的连接。
      - `onOpen`：发送 `ClientStatus("ready")`，随后发送一次 `ClientCapabilities`。
      - `onMessage`：解析 JSON 命令，目前关心：
        - `"start_capture"`：调用 `startStreaming(width, height, bitrate, fps)`。
        - `"stop_capture"`：调用 `stopStreaming()`。
    - 能力上报 `sendCapabilities()` / `buildCapabilitiesJson()`：
      - 使用 `CameraManager` 枚举设备所有相机的 `YUV_420_888` 输出分辨率；
      - 以 JSON 形式发送至服务器，便于服务器决策分辨率。
    - 推流控制 `startStreaming(width, height, bitrate, fps)`：
      - 记录服务器要求的分辨率、码率、目标 FPS（`fps<=0` 视为“unlimited”）；
      - 创建 `ImageAnalysis`：
        - `setTargetResolution(Size(width, height))`
        - `setBackpressureStrategy(STRATEGY_KEEP_ONLY_LATEST)`，保证只处理最新帧；
      - 在 `setAnalyzer` 中：
        - 先通过 `shouldSendFrame(targetFps)` 判断是否需要丢帧：
          - `targetFps <= 0`：不过滤，全部尝试发送；
          - `targetFps > 0`：通过 `System.nanoTime()` 控制最小时间间隔，丢弃多余帧；
        - 由于使用了 **ViewPort + UseCaseGroup**，`imageProxy.cropRect` 已经对应统一后的取景窗口，`computeCropRect()` 仅做偶数对齐和越界保护，不再额外改变 FOV；
        - 首帧时以裁剪后的尺寸启动 `H264Encoder`，确保编码分辨率与预览一致；
        - 调用 `encoder.encode(imageProxy, cropRect)` 完成编码；
        - 所有路径最终都会在 `finally` 中 `imageProxy.close()`，避免阻塞 CameraX。
      - 编码回调中：
        - 为每帧构造 16 字节二进制帧头（大端）：
          - `int64 timestampMs`
          - `int32 frameSequence`（低 32 位递增）
          - `int32 payloadSize`
        - 之后紧跟 H.264 裸码流，共同通过 WebSocket 发送给服务器。
      - 更新 UI 状态 `statusMessage`，例如：`"Streaming H.264 at 1600x1200 (5fps)"`。
    - 停止推流 `stopStreaming()`：
      - 在主线程清空 Analyzer，停止相机分析；
      - 停止并释放编码器，重置 FPS 控制状态；
      - 向服务器发送 `ClientStatus("capture_stopped", ...)`。
  - **图像处理辅助**
    - `ImageProxy.toNv12ByteArray(cropRect: Rect)`：
      - 仅对 `cropRect` 区域做 YUV_420_888 → NV12 转换；
      - Y 分量逐行复制，UV 分量按 2×2 block 采样，写成交错的 UV；
      - 强制宽高为偶数，避免硬件编码对齐问题。
    - `computeCropRect(imageProxy: ImageProxy)`：
      - **注意**：由于使用了 ViewPort + UseCaseGroup，`imageProxy.cropRect` 已经对应统一后的取景窗口（与预览 FOV 一致）；
      - 此函数以 `imageProxy.cropRect` 为基础，仅做偶数对齐和越界保护，不再额外改变 FOV；
      - 所有坐标与结果宽高保证为偶数；若裁剪失败则退回“整帧的最近偶数尺寸”。
    - `shouldSendFrame(targetFps: Int)`：
      - 使用 `lastFrameSentTimeNs` 与 `System.nanoTime()` 控制最小发送间隔；
      - `targetFps <= 0` 则直接返回 true，表示不过滤。

- 其他关键文件
  - `app/src/main/res/xml/network_security_config.xml`：开发环境下允许访问指定明文 HTTP/WebSocket 域名。
  - `app/src/main/AndroidManifest.xml`：权限声明（相机、网络）及网络安全配置引用。
  - `app/build.gradle.kts`：模块依赖定义（CameraX、Compose、OkHttp 等）。

---

## 与后端的通信协议

### 1. 能力上报（App → Server）

App 建立 WebSocket 连接后，会主动发送一次 JSON 能力描述：

```json
{
  "type": "capabilities",
  "deviceModel": "Pixel 6a",
  "sdkInt": 35,
  "resolutions": [
    {
      "width": 4032,
      "height": 3024,
      "format": "YUV_420_888",
      "lensFacing": "back"
    },
    {
      "width": 1920,
      "height": 1080,
      "format": "YUV_420_888",
      "lensFacing": "back"
    }
    // ...
  ],
  "imageAnalysisResolution": {
    "width": 1920,
    "height": 1920
  }
}
```

- `resolutions`：设备硬件支持的所有 YUV_420_888 分辨率列表，按面积从大到小排序
- `imageAnalysisResolution`：ImageAnalysis 实际使用的分辨率（App 在获取相机权限后会立即采集一帧以获取实际分辨率，如果尚未获取则使用预期分辨率）。该值会根据当前选择的摄像头（后置/前置）自动更新，切换摄像头时会重新初始化并获取新摄像头的实际分辨率。

服务器仅需解析其中感兴趣的分辨率即可。

### 2. 控制命令（Server → App）

服务器在终端输入：

```text
# 使用 App 当前选择的宽高比（4:3、16:9 或不裁剪），码率 4 MB，FPS 10
start

# 显式指定宽高比为 4:3，码率 4 MB，FPS 10
start 4:3 4 10

# 显式指定宽高比为 16:9，码率 4 MB，FPS 10
start 16:9 4 10

# 显式指定为不裁剪（1:1），码率 4 MB，FPS 10
start 1:1 4 10
```

会广播给所有客户端如下 JSON（当提供宽高比时）：

```json
{
  "command": "start_capture",
  "payload": {
    "format": "h264",
    "aspectRatio": { "width": 4, "height": 3 },
    "bitrate": 4,
    "fps": 10
  }
}
```

（当不提供宽高比时，`aspectRatio` 字段会被省略）

- **参数含义**
  - `format`: 当前固定为 `"h264"`。
  - `aspectRatio`: 可选，目标宽高比（例如 `4:3`、`16:9`、`1:1`）。如果提供，App 会使用该宽高比进行录制，并更新 UI 中的宽高比选择。如果不提供，App 会使用当前 UI 中选择的宽高比。`1:1` 表示不裁剪（使用全帧（我们假定ImageAnalysis全帧比例是1:1），但做 32 对齐）。
  - `bitrate`: 目标码率（单位 MB，例如 `4` 表示 4 MB/s）。App 会将其转换为 bps（`bitrate * 1000000`）后传给 `MediaFormat.KEY_BIT_RATE`。
  - `fps`:
    - `> 0`：Analyzer 层按该值限制发送帧率，多余帧被丢弃；
    - `0` 或缺省：不限帧率，尽量多发。

停止推流时，服务器发送：

```json
{ "command": "stop_capture" }
```

### 3. 状态上报（App → Server）

App 在关键状态变更时发送 `ClientStatus`：

- 连接建立后：

```json
{ "status": "ready", "message": "Client is ready to stream" }
```

- 开始推流时：

```json
{
  "status": "capture_started",
  "message": "Streaming H.264 at 4:3 aspect ratio, 4MB bitrate (10fps)",
  "rotation": 90
}
```

  - `rotation`: 设备旋转角度（0、90、180、270），表示视频需要旋转多少度才能正过来。App 在发送 `capture_started` 时就会根据设备物理方向计算并包含正确的 rotation 值。

- 停止推流时：

```json
{
  "status": "capture_stopped",
  "message": "Streaming has been stopped by client/server."
}
```

服务器通过这些状态来创建 / 结束录制会话，并根据 rotation 值在封装 MP4 时进行视频旋转。

### 4. 帧数据（App → Server）

每一帧通过 WebSocket 以二进制方式发送，结构为：

```text
16 字节帧头（大端） + H.264 NAL 裸码流
```

帧头具体字段：

- `int64 timestampMs`：设备时间戳，单位毫秒（基于编码器输出 `presentationTimeUs`）。
- `int32 frameSequence`：帧序号，低 32 位循环递增。
- `int32 payloadSize`：后续 H.264 负载的字节数。

后端的 `parse_frame_packet()` 会按同样的结构解出时间戳 / 帧号 / 负载。

---

## 运行与联调步骤（简版）

1. **启动后端（在 `backend/` 目录）**

   ```bash
   pip install -r requirements.txt
   python server.py
   ```

   看到输出：

   ```text
   WebSocket server started at ws://0.0.0.0:50001
   You can now connect your Android Camera App.
   ```

2. **在 Android Studio 中运行 App**
   - 克隆后，用 Android Studio 打开 `lab-log/android-camera/` 目录，而不是 `lab-log/`。等待 Gradle 同步完成。
   - 连接真机或启动模拟器。
   - 点击 Run 安装并启动 App。

3. **在 App 中配置服务器 URL**
   - 主界面输入框中填入 WebSocket URL，例如：
     - 局域网：`ws://192.168.1.10:50001/android-cam`
     - 公网：`ws://your_public_ip_or_domain:50001/android-cam`
   - 开关拨到 ON，连接成功后状态会显示 `Connected, ready for command`。

4. **相机预览、摄像头选择与宽高比选择**
   - 授予相机权限后，预览会自动显示在主界面顶部的**正方形区域**中；
   - 预览下方有**摄像头选择**（提供 后置 / 前置 两个选项），**默认后置**；录制时按钮禁用，无法切换；
   - 摄像头选择下方有**宽高比选择**（提供 4:3 / 16:9 / 不裁剪 三种选项），**默认 4:3**；录制时按钮禁用，无法切换；
   - **4:3 和 16:9**：预览画面会以 **FIT 方式完整显示** 在正方形 Box 内，可能出现上下/左右黑边，但不会被裁剪；实际录制时会根据选择的宽高比进行安全尺寸裁剪（32/偶数对齐）；
   - **不裁剪**：使用全帧（不裁剪），但做 32 对齐以避免条纹，虚线框显示为正方形；适用于需要最大视场的场景；
   - **重要**：预览使用的宽高比与实际编码发送到服务器的视频完全一致，用户在预览中看到的取景范围就是最终录制的范围。

5. **从服务器开始录制**
   - 在 `backend/server.py` 运行的终端输入，例如：

     ```text
     # 使用 App 当前选择的宽高比（4:3、16:9 或不裁剪），码率 4 MB，FPS 10
     start

     # 显式指定宽高比为 4:3，码率 4 MB，FPS 10
     start 4:3 4 10

     # 显式指定宽高比为 16:9，码率 4 MB，FPS 10
     start 16:9 4 10

     # 显式指定为不裁剪（1:1），码率 4 MB，FPS 10
     start 1:1 4 10
     ```

   - 终端会看到类似：

     ```text
     [App Status] ... {"status":"capture_started","message":"Streaming H.264 at 4:3 aspect ratio, 4MB bitrate (10fps)","rotation":90}
     [Info]: Started recording session at recordings/... (rotation=90)
     [Frame]: ... seq=0 timestamp=... size=...
     ...
     ```

6. **停止并查看 MP4**
   - 在终端输入：

     ```text
     stop
     ```

   - 服务器会结束会话并打印：

     ```text
     [Info]: FPS estimate (server) frame_count=57 -> 4.81
     [Info]: Rotating video by 90 degrees (transpose=1)
     [Info]: Thumbnail saved to recordings/<client>_<timestamp>/thumbnail.jpg
     [Info]: MP4 saved to recordings/<client>_<timestamp>/stream.mp4
     ```

   - 到 `backend/recordings/` 目录下即可找到对应的文件夹，包含：
     - `stream.h264`：原始 H.264 流
     - `stream.mp4`：封装后的 MP4 视频（已根据 rotation 旋转）
     - `thumbnail.jpg`：第一帧的缩略图（已根据 rotation 旋转）

---

## 开发经验与注意事项

### 视频旋转（Rotation）处理

#### 如何正确获取 rotation 值

1. **不要使用 `imageProxy.imageInfo.rotationDegrees` 直接作为 rotation**：
   - `imageProxy.imageInfo.rotationDegrees` 表示相机传感器相对于屏幕的旋转
   - 当屏幕方向被锁定时，该值可能不会随设备物理旋转而变化
   - 直接使用会导致所有方向都返回相同的 rotation 值（通常是 90）

2. **正确方法：使用设备物理方向计算 rotation**：
   - 使用 `OrientationEventListener` 检测设备的物理方向（相对于重力）
   - 根据摄像头类型使用不同的公式：
     - **后置摄像头**：`rotationForBackend = (physicalRotation + 90) % 360`
     - **前置摄像头**：
       - 竖放（0°）或倒放（180°）：`rotationForBackend = (physicalRotation + 90 + 180) % 360`
       - 左横（270°）或右横（90°）：`rotationForBackend = (physicalRotation + 90) % 360`
   - 其中 `physicalRotation` 为：
     - `0`：设备竖放（正常）
     - `90`：设备右横（顺时针旋转 90 度）
     - `180`：设备倒置
     - `270`：设备左横（逆时针旋转 90 度）

3. **rotation 值的含义**：
   - `0`：不需要旋转（视频已经是正确的方向）
   - `90`：需要顺时针旋转 90 度
   - `180`：需要旋转 180 度
   - `270`：需要逆时针旋转 90 度（或顺时针 270 度）

#### 设备方向与 rotation 的对应关系

根据实际测试结果：

**后置摄像头**：
- **设备竖放（0°）** → rotation = 90（需要旋转 90 度才能正过来）
- **设备右横（90°）** → rotation = 180（需要旋转 180 度才能正过来）
- **设备倒置（180°）** → rotation = 270（需要旋转 270 度才能正过来）
- **设备左横（270°）** → rotation = 0（不需要旋转，视频已经是正确的方向）

**前置摄像头**：
- **设备竖放（0°）** → rotation = 270（需要旋转 270 度才能正过来）
- **设备右横（90°）** → rotation = 180（需要旋转 180 度才能正过来）
- **设备倒置（180°）** → rotation = 90（需要旋转 90 度才能正过来）
- **设备左横（270°）** → rotation = 0（不需要旋转，视频已经是正确的方向）

> **注意**：
> - 后置摄像头：手机左横时 rotation 为 0，而不是 180。这是因为相机传感器通常是横向安装的，当设备左横时，传感器相对于重力的方向恰好是 0 度。
> - 前置摄像头：竖放和倒放需要额外旋转 180 度，而左横和右横使用与后置相同的公式。这是因为前置摄像头的传感器安装方向与后置不同。

#### 后端处理 rotation

后端使用 ffmpeg 的 `transpose` 滤镜来处理旋转：

- `rotation = 90`：使用 `transpose=1`（顺时针旋转 90 度）
- `rotation = 180`：使用 `transpose=1,transpose=1`（两次 90 度旋转）
- `rotation = 270`：使用 `transpose=2`（逆时针旋转 90 度）
- `rotation = 0`：不旋转，直接拷贝（使用 `-c:v copy`，无需重新编码，速度最快）

**性能优化建议**：

- **rotation = 0** 时，后端使用 `-c:v copy` 直接拷贝视频流，无需重新编码，速度最快（几乎瞬间完成）。
- **rotation ≠ 0** 时，后端需要重新编码视频以完成旋转，速度较慢。可以通过以下方式优化：
  - **硬件加速编码**：如果服务器有 GPU，可以使用硬件编码器（如 `h264_nvenc`、`h264_qsv` 等）代替软件编码器 `libx264`。
  - **更快的编码预设**：将 `-preset fast` 改为 `-preset veryfast` 或 `-preset ultrafast`（速度更快但文件更大）。
  - **调整 CRF 值**：将 `-crf 18` 改为 `-crf 23`（编码更快但质量略低）。
  - **注意**：如果视频需要发送给大模型处理，必须使用像素级旋转（重新编码），不能使用 MP4 旋转元数据，因为大多数视频处理库不会自动应用旋转元数据。

### 条纹伪影和绿色条带（Stripe Artifacts & Green Bands）问题

条纹伪影和绿色条带是视频编码中常见的视觉问题，表现为画面中出现水平或垂直的彩色条纹，或视频底部出现绿色条带。在本项目中，以下情况可能导致这些问题：

#### 主要原因

1. **裁剪尺寸与编码器 stride 不匹配**：
   - **问题**：硬件编码器（如 Exynos）内部使用特定的 stride（例如 1472），如果裁剪后的宽度（如 1440）与 stride 不匹配，会导致硬件内部对齐时产生伪影
   - **现象**：竖屏录制时出现条纹/绿带，横屏正常
   - **解决方案**：
     - 使用"安全尺寸"而非精确比例：竖屏使用 1472×1920，横屏使用 1920×1472（或 16:9 时使用 1920×1088）
     - 确保裁剪尺寸是 32 的倍数且为偶数（32/偶数对齐）
     - 避免使用精确的 4:3 比例（如 1440×1920），优先使用与编码器 stride 兼容的尺寸

2. **手动旋转 YUV 数据**：
   - **问题**：在 Android 端手动旋转 YUV_420_888 或 NV12 数据时，如果处理不当会导致条纹伪影
   - **原因**：YUV 数据的 stride（行对齐）和像素对齐要求很严格，手动旋转时如果忽略 stride 或对齐要求，会导致数据错位
   - **解决方案**：避免在 Android 端手动旋转 YUV 数据，将旋转交给后端的 ffmpeg 处理

3. **HAL 旋转与手动裁剪叠加**：
   - **问题**：同时使用 `SCALER_ROTATE_AND_CROP`（HAL 级旋转）和手动裁剪时，可能导致双重旋转/裁剪冲突
   - **现象**：横竖屏都出现条纹
   - **解决方案**：
     - 固定 `ImageAnalysis` 的 `targetRotation` 为 `Surface.ROTATION_0`
     - 停用 HAL 级旋转裁剪（注释掉 `applyRotateAndCrop`）
     - 仅在前端做安全尺寸裁剪，旋转完全由后端 ffmpeg 处理

4. **色度平面顺序错误**：
   - **问题**：某些设备的 YUV_420_888 映射可能更接近 NV21（VU 顺序），而编码器期望 NV12（UV 顺序）
   - **现象**：出现绿色或紫色条纹
   - **解决方案**：
     - 使用正确的平面顺序：`planes[1]` 作为 U，`planes[2]` 作为 V
     - 写入顺序为 U 后 V（NV12 格式）
     - 如果仍有问题，可尝试交换 U/V 顺序（NV21）进行测试

5. **裁剪尺寸对齐不足**：
   - **问题**：如果裁剪后的视频尺寸不是编码器要求的对齐值，可能导致条纹伪影
   - **现象**：视频底部出现绿色条带
   - **解决方案**：
     - 确保裁剪后的宽度和高度都是 32 的倍数且为偶数（32/偶数对齐）
     - 对于某些编码器，可能需要 64 对齐（但会损失更多视场）
     - 所有裁剪坐标（left, top）也必须为偶数

6. **Stride 处理不当**：
   - **问题**：YUV_420_888 格式中，Y 平面和 UV 平面可能有不同的 stride
   - **现象**：如果直接按宽度复制数据而忽略 stride，会导致数据错位
   - **解决方案**：在复制 YUV 数据时，必须考虑 stride，逐行复制而不是按宽度复制

7. **编码器配置问题**：
   - **问题**：如果编码器的颜色格式配置不正确，也可能导致条纹伪影
   - **解决方案**：确保编码器配置的颜色格式与输入数据格式匹配（使用 `COLOR_FormatYUV420SemiPlanar` 对应 NV12）

#### 当前实现的安全策略

为了避免条纹和绿带，当前代码采用了以下安全策略：

1. **安全尺寸裁剪**：
   - 4:3 比例：竖屏 1472×1920，横屏 1920×1472
   - 16:9 比例：竖屏 1088×1920，横屏 1920×1088
   - 不裁剪（1:1）：使用全帧，宽高分别向下对齐到 32 的倍数且为偶数（例如 1920×1920 或 4032×3008）
   - 所有尺寸均为 32 的倍数且为偶数

2. **固定旋转设置**：
   - `ImageAnalysis` 的 `targetRotation` 固定为 `Surface.ROTATION_0`
   - 停用 HAL 级旋转裁剪
   - 旋转完全由后端 ffmpeg 根据 `rotation` 值处理

3. **正确的色度格式**：
   - 使用 NV12 格式（planes[1]=U, planes[2]=V，写入顺序 U 后 V）
   - 编码器配置为 `COLOR_FormatYUV420SemiPlanar`

4. **严格的坐标对齐**：
   - 所有裁剪坐标和尺寸均为偶数
   - 裁剪尺寸向下对齐到 32 的倍数
   - 居中裁剪，确保坐标不越界

> **经验总结**：
> - 优先使用"安全尺寸"而非精确比例，避免与编码器 stride 冲突
> - 避免在 Android 端进行任何旋转操作，将所有旋转交给后端 ffmpeg 处理
> - 确保所有裁剪尺寸和坐标都满足对齐要求（32/偶数对齐）
> - 如果遇到条纹/绿带，优先检查裁剪尺寸是否与编码器 stride 匹配
> - 测试时可以先使用全帧对齐（无裁剪）验证是否消除问题，再逐步缩小到目标尺寸

---

## 关键依赖与版本

- **语言 / 运行时**
  - Kotlin（与项目中 Gradle 配置保持一致）
  - **最低支持 Android 7.0 (API 24)**，目标版本 Android 15 (API 36)
  - Android SDK 33+（建议）
- **主要库**
  - CameraX：`camera-core` / `camera-camera2` / `camera-lifecycle` / `camera-view`
  - Jetpack Compose：`material3`、`runtime`、`ui` 等
  - Accompanist Permissions：相机权限请求
  - OkHttp WebSocket：网络通信
- **后端**
  - Python 3.x
  - `websockets`
  - 已安装 `ffmpeg`（在服务器上可通过命令行直接执行 `ffmpeg`）
