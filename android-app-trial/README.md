# Lab Log Android Camera（手机采集视频并推流）

手机端使用 CameraX + MediaCodec 采集并编码 H.264 视频，使用 MediaMuxer 封装为 MP4 分段，通过 WebSocket 推送到 Python 服务器；  
同时使用 ML Kit 实时识别用户二维码，识别结果随 MP4 分段元数据一起上报；  
服务器接收 MP4 分段和二维码识别结果，根据配置决定是否实时处理和索引。

---

## 整体架构概览

- **Android 端（本目录 `android-camera/`）**
  - Kotlin + Jetpack Compose UI
  - CameraX 负责相机预览 + YUV 图像采集
  - MediaCodec 负责 H.264 硬件编码
  - MediaMuxer 负责 MP4 分段封装
  - ML Kit 负责实时二维码识别
  - OkHttp WebSocket 负责与服务器通信
- **后端（`streaming_server/server.py`）**
  - 使用 `websockets` 库实现 WebSocket 服务器
  - 接收来自手机的 MP4 分段（包含二维码识别结果），保存到 `recordings/`
  - 支持实时处理和索引，或仅保存视频分段

数据流大致如下：

1. App 启动并获取相机权限后，会立即初始化临时 ImageAnalysis 采集一帧以获取实际分辨率（根据当前选择的摄像头），并在连接后端时通过能力上报发送该信息；
2. 服务器从终端输入 `start [WIDTH:HEIGHT] [BITRATE_MB] [FPS]`（例如 `start 4:3 4 10` 或 `start 1:1 4 10` 或 `start`），向所有客户端广播 `start_capture` 命令；
3. App 收到命令后：
   - 如果命令中包含 `aspectRatio`，更新 UI 中的宽高比选择并用于录制；否则使用当前 UI 中选择的宽高比（4:3、16:9 或不裁剪）；
   - 记录服务端要求的目标宽高比 / 码率（MB） / FPS；
   - 根据当前选择的摄像头（后置/前置）创建 ImageAnalysis 和 Preview；
   - 相机预览嵌入在主界面顶部的**正方形区域**中，预览区域宽高比自动匹配选择的宽高比（4:3、16:9 或不裁剪时显示为正方形）；
   - 使用 CameraX **ViewPort + UseCaseGroup** 确保预览（Preview）和采集（ImageAnalysis）的 FOV 完全一致，用户在预览中看到的画面就是发送到服务器的画面；
   - 在 `ImageAnalysis` 分析流中按需丢帧，并根据选择的宽高比进行安全尺寸裁剪（4:3/16:9 时裁剪，不裁剪时使用全帧但做 32 对齐）；
   - 根据设备物理方向和摄像头类型在 Android 端完成视频旋转，确保发送到服务器的视频已经是正确方向；
   - 使用 MediaCodec 编码 H.264，MediaMuxer 封装为 MP4 分段（约 60 秒），每个分段在关键帧处分割，确保独立可解码；
   - 在 `ImageAnalysis` 中实时识别二维码（使用 ML Kit），按分段聚合识别结果（同一用户保留最高置信度），随 MP4 分段元数据一起上报；
   - 识别成功时播放提示音并在预览层显示"已识别用户"提示；
   - 通过 WebSocket 发送 MP4 分段（Base64 编码）及二维码识别结果；
4. 服务器端：
   - 接收 MP4 分段和二维码识别结果，保存到 `recordings/` 目录；
   - 根据配置决定是否实时处理和索引视频内容；
   - 视频已在 Android 端旋转完成，无需后端再旋转。

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
    - 使用 `MediaCodec` 进行 H.264 硬件编码。
    - **色彩格式自适应**：检测编码器实际输入色彩格式，如果为 `COLOR_FormatYUV420Planar`（I420），自动将 NV12 转换为 I420；否则直接使用 NV12。
    - `start(width, height, bitrate, targetFps)`：配置编码器；`targetFps<=0` 时使用默认 10fps 作为编码参考。
    - `encode(image: ImageProxy, cropRect: Rect)`：
      - 调用扩展函数 `ImageProxy.toNv12ByteArray(cropRect)` 将 YUV_420_888 转为 NV12；
      - 根据编码器格式要求，必要时转换为 I420；
      - 使用实际帧时间戳（`image.imageInfo.timestamp`）而非固定间隔，确保视频时间轴准确；
      - 送入编码器，循环读取输出缓冲区；
      - 将编码好的字节及时间戳通过回调传出。
    - `stop()`：安全停止并释放编码器。
  - **二维码识别 `QrDetection`**
    - 使用 ML Kit Barcode Scanning（版本 17.3.0+）实时识别二维码。
    - 在 `ImageAnalysis` 中按 300ms 间隔采样帧进行识别，避免性能开销过大。
    - 解析二维码内容（JSON 格式），提取 `user_id` 和 `public_key_fingerprint` 用于去重。
    - 按分段聚合识别结果，同一用户（基于 user_id + public_key_fingerprint）在同一分段内只保留置信度最高的结果。
    - 识别成功时播放系统提示音（主线程）并在预览层显示提示。
    - 识别结果包含：`user_id`、`public_key_fingerprint`、`confidence`、`detected_at_ms`（绝对时间戳）、`detected_at`（ISO 格式文本）。
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
        - 使用 MediaMuxer 将编码后的 H.264 帧封装为 MP4 分段（约 60 秒，在关键帧处分割）；
        - 每个分段包含完整的 SPS/PPS（在关键帧前置），确保独立可解码；
        - 分段完成后，将 MP4 数据 Base64 编码，连同二维码识别结果（`qr_results` 数组）一起通过 WebSocket 发送给服务器。
      - 二维码识别：
        - 在 `ImageAnalysis` 分析器中按 300ms 间隔采样帧进行识别；
        - 识别结果缓存到当前分段的去重映射中（按 user_id + public_key_fingerprint 去重，保留最高置信度）；
        - 识别成功时播放提示音（主线程）并显示 UI 提示。
      - 更新 UI 状态 `statusMessage`，例如：`"Streaming H.264 at 1600x1200 (5fps)"`。
    - 停止推流 `stopStreaming()`：
      - 在主线程清空 Analyzer，停止相机分析；
      - 停止并释放编码器，重置 FPS 控制状态；
      - 向服务器发送 `ClientStatus("capture_stopped", ...)`。
  - **图像处理辅助**
    - **OCR-B 字体渲染器 `OcrBFontRenderer`**（新增）
      - 负责从 TrueType 字体文件加载字体并渲染字符位图；
      - 在应用启动时预加载所有时间戳所需的字符（数字 0-9、冒号、空格、T/i/m/e）；
      - 使用 Android Canvas + Paint 实现高质量抗锯齿渲染；
      - 字体加载失败时自动回退到系统等宽字体（`Typeface.MONOSPACE`）；
      - 关键方法：
        - `initialize(context: Context)`：初始化字体
        - `preloadAllCharacters(width: Int, height: Int)`：预加载所有字符
        - `getCachedCharBitmap(char: Char)`：获取缓存的字符位图
        - `isPreloadCompleted()`：检查预加载是否完成
    - `ImageProxy.toNv12ByteArray(cropRect: Rect, rotationDegrees: Int, timestamp: String?, charWidth: Int, charHeight: Int)`：
      - 仅对 `cropRect` 区域做 YUV_420_888 → NV12 转换；
      - 支持旋转（0、90、180、270 度）：先旋转整个图像，然后从旋转后的图像中裁剪指定区域；
      - Y 分量逐行复制，UV 分量按 2×2 block 采样，写成交错的 UV；
      - 强制宽高为偶数，避免硬件编码对齐问题；
      - 如果提供了 `timestamp`，会在 Y 平面上绘制 OCR-B 字体时间戳水印（白色文字配黑色背景，左上角显示）。
    - `computeCropRect(imageProxy: ImageProxy)`：
      - **注意**：由于使用了 ViewPort + UseCaseGroup，`imageProxy.cropRect` 已经对应统一后的取景窗口（与预览 FOV 一致）；
      - 此函数以 `imageProxy.cropRect` 为基础，仅做偶数对齐和越界保护，不再额外改变 FOV；
      - 所有坐标与结果宽高保证为偶数；若裁剪失败则退回"整帧的最近偶数尺寸"。
    - `shouldSendFrame(targetFps: Int)`：
      - 使用 `lastFrameSentTimeNs` 与 `System.nanoTime()` 控制最小发送间隔；
      - `targetFps <= 0` 则直接返回 true，表示不过滤。
    - **时间戳水印功能**：
      - 支持在视频帧上绘制时间戳，格式为 "Time: hh:mm:ss"（24 小时格式）；
      - 时间戳显示在视频左上角，使用白色文字配黑色背景以提高可读性；
      - 使用 OCR-B 字体（ISO 1073/2 标准），专为光学字符识别设计，确保视觉大模型高识别准确率；
      - 支持多种模式切换（**编译时配置**，在 `WebSocketViewModel` 中修改 `timestampMode` 变量，需要重新编译）：
        - `TIMESTAMP_MODE_NONE`：无时间戳
        - `TIMESTAMP_MODE_OCRB_16x24`：使用 OCR-B 16×24 像素字体
        - `TIMESTAMP_MODE_OCRB_20x30`：使用 OCR-B 20×30 像素字体（默认）
      - 字符位图在应用启动时预加载（后台线程），运行时零渲染开销；
      - 时间戳每秒更新一次，使用缓存机制减少字符串格式化开销。

- 其他关键文件
  - `app/src/main/res/xml/network_security_config.xml`：开发环境下允许访问指定明文 HTTP/WebSocket 域名。**重要**：如果更换开发服务器（尤其是更换服务器域名），需要在编译前修改此文件中的域名配置，否则应用将无法连接到新的服务器。详见下方"开发经验与注意事项"章节。
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
  "message": "Streaming H.264 at 4:3 aspect ratio, 4MB bitrate (10fps) [rotated on Android]"
}
```

  - 视频已在 Android 端旋转完成，无需发送 rotation 值。

- 停止推流时：

```json
{
  "status": "capture_stopped",
  "message": "Streaming has been stopped by client/server."
}
```

服务器通过这些状态来创建 / 结束录制会话，并直接封装成 MP4（无需旋转）。

### 4. MP4 分段数据（App → Server）

每个 MP4 分段（约 60 秒）通过 WebSocket 以 JSON 文本消息发送：

```json
{
  "type": "mp4_segment",
  "segment_id": "segment_001",
  "data": "base64_encoded_mp4_data...",
  "size": 1234567,
  "qr_results": [
    {
      "user_id": "user123",
      "public_key_fingerprint": "abc123...",
      "confidence": 0.95,
      "detected_at_ms": 1734901234567,
      "detected_at": "2025-12-23T04:14:30.123+08:00"
    }
  ]
}
```

字段说明：
- `type`：固定为 `"mp4_segment"`。
- `segment_id`：分段标识符，用于区分不同分段。
- `data`：MP4 文件的 Base64 编码数据。
- `size`：MP4 文件大小（字节）。
- `qr_results`：二维码识别结果数组，每个分段内按 `user_id` + `public_key_fingerprint` 去重，只保留置信度最高的结果。
  - `user_id`：用户 ID（从二维码 JSON 中解析，可选）。
  - `public_key_fingerprint`：公钥指纹（从二维码 JSON 中解析，可选）。
  - `confidence`：置信度（基于二维码边界框面积计算）。
  - `detected_at_ms`：检测时间戳（毫秒，绝对时间，与视频水印时间对齐）。
  - `detected_at`：检测时间戳（ISO 8601 格式文本）。

**注意**：MP4 分段已在 Android 端完成封装，包含完整的 SPS/PPS（在关键帧前置），确保每个分段独立可解码。视频已在 Android 端旋转完成，无需后端再旋转。

---

## 运行与联调步骤（简版）

1. **启动后端（在 `streaming_server/` 目录）**

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
   - 在 `streaming_server/server.py` 运行的终端输入，例如：

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
     [App Status] ... {"status":"capture_started","message":"Streaming H.264 at 4:3 aspect ratio, 4MB bitrate (10fps) [rotated on Android]"}
     [Info]: Started recording session at recordings/...
     [MP4 Segment]: segment_id=... size=... qr_results=...
     ...
     ```

6. **停止并查看 MP4**
   - 在终端输入：

     ```text
     stop
     ```

   - 服务器会结束会话并打印：

     ```text
     [Info]: Received X MP4 segments
     [Info]: MP4 segments saved to recordings/<client>_<timestamp>/
     ```

   - 到 `streaming_server/recordings/` 目录下即可找到对应的文件夹，包含：
     - `segment_00.mp4`、`segment_01.mp4` 等：MP4 分段文件（视频已在 Android 端旋转完成，无需后端再旋转）
     - 每个分段包含完整的 SPS/PPS，可独立解码
     - 如果启用了二维码识别，服务器日志会显示识别结果（`qr_results`）

---

## 开发经验与注意事项

### 网络安全配置（network_security_config.xml）

**重要提醒**：本应用在开发阶段使用明文 WebSocket（`ws://`）连接，因为使用`wss://`需要使用证书，而证书的申请和安装比较麻烦。而使用明文 WebSocket需要在 `app/src/main/res/xml/network_security_config.xml` 中配置允许访问的域名，因为Android 9+ 默认禁止明文流量。

#### 配置文件位置
- `app/src/main/res/xml/network_security_config.xml`

#### 更换开发服务器时的操作步骤

**如果更换开发服务器（尤其是更换服务器域名），必须在编译前修改此配置文件**：

1. **打开配置文件**：
   - 路径：`app/src/main/res/xml/network_security_config.xml`

2. **修改域名**：
   - 将 `<domain>` 标签中的域名替换为新的服务器域名
   - 例如，如果新服务器域名为 `new-server.example.com`，则修改为：
     ```xml
     <domain includeSubdomains="true">new-server.example.com</domain>
     ```

3. **重新编译**：
   - 修改后需要重新编译应用（`Build > Rebuild Project`）
   - 如果只修改了资源文件，也可以直接运行，Android Studio 会自动重新打包

#### 生产环境建议

生产环境应改用 `wss://`（WebSocket Secure），然后可以移除 `network_security_config.xml` 文件和`android:networkSecurityConfig` 引用。

### 旧设备安装问题（INSTALL_FAILED_TEST_ONLY）

在某些旧设备（如 Android 8.1 设备）上，通过 Android Studio 的 Run 按钮直接安装可能会遇到 `INSTALL_FAILED_TEST_ONLY` 错误。不过，这个问题大概仅限于调试阶段，正式发布的APK在安装时大概不会遇到。

**问题原因**：
- Android Studio 的 Run 默认使用 `intermediates` 目录的中间 APK，可能被标记为 testOnly
- 旧版本的 Android 系统对 test-only APK 的安装限制更严格

**解决方案**：
使用自定义 Run 配置，在安装前执行 `assembleDebug` 任务生成最终的 APK：
1. Run → Edit Configurations...
2. 创建新配置
3. Name: "Install from Outputs"，Module: 选择你的 app 模块
3. 在 "Before launch" 中添加：
   - 点击 "+" → Run Gradle Task
   - Gradle project: 选择 `android-camera:app` 模块
   - Tasks: `assembleDebug`
4. 保存并使用此配置运行

这样会确保安装使用的是 `outputs` 目录的最终 APK，而不是 `intermediates` 目录的中间 APK，从而避免 testOnly 标志问题。

**替代方案**：
也可以使用 `Build → Generate App Bundles or APKs → Generate APKs` 构建后，手动通过 adb 安装：
```bash
adb install app\build\outputs\apk\debug\app-debug.apk
```

### 视频旋转（Rotation）处理（已验证四姿态正常）

#### 现行策略

- **预览/取景**：`targetRotation` 使用当前显示方向（Display rotation），保证预览与屏幕一致，避免与物理方向叠加导致误转。  
- **编码/采集**：使用设备物理方向 + 摄像头映射计算 `rotationForBackend`，完全基于 `calculateRotationForBackend(physicalRotation, facing)`，不依赖 `imageProxy.imageInfo.rotationDegrees`，避免 HAL/显示旋转重复叠加。  
- **公式（未变）**：  
  - 后置：`(physicalRotation + 90) % 360`  
  - 前置：竖/倒：`(physicalRotation + 90 + 180) % 360`；左/右横：`(physicalRotation + 90) % 360`

实测：竖直、左横、右横、倒置四种姿态下，预览与采集视频方向均与现实一致。

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

#### Android 端旋转处理

视频旋转在 Android 端完成，通过手动旋转 YUV 数据实现：

- 编码前统一使用 `rotationForBackend`（见上公式）作为旋转角度；预览使用 Display rotation，不会干扰编码旋转。  
- 在 `toNv12ByteArray()` 中按 0/90/180/270 度旋转 YUV，旋转后再按目标宽高比裁剪并 32/偶数对齐。  
- 发送到后端的视频已经是正确方向，后端无需再旋转。

**优势**：

- 后端处理速度快：始终使用 `-c:v copy` 直接拷贝视频流，无需重新编码，几乎瞬间完成
- 适合大模型处理：视频已经是像素级旋转，无需担心 MP4 旋转元数据不被支持的问题
- 减少服务器负载：旋转在客户端完成，不占用服务器 CPU/GPU 资源

### 条纹伪影和绿色条带（Stripe Artifacts & Green Bands）问题

条纹伪影和绿色条带是视频编码中常见的视觉问题，表现为画面中出现水平或垂直的彩色条纹，或视频底部出现绿色条带。在本项目中，以下情况可能导致这些问题：

#### 主要原因

1. **裁剪尺寸与编码器对齐要求不匹配**：
   - **问题**：硬件编码器要求视频尺寸必须是 32 的倍数且为偶数。如果裁剪后的尺寸不满足这个要求（如 1080 = 32 × 33.75），会导致硬件编码器内部对齐时产生绿色条带
   - **现象**：视频底部出现绿色条带
   - **解决方案**：
     - 使用满足 32 对齐的尺寸：4:3 使用 1920×1440（1440 = 32 × 45），16:9 使用 1920×1088（1088 = 32 × 34）
     - 确保裁剪尺寸是 32 的倍数且为偶数（32/偶数对齐）
     - 测试发现：1920×1440 无问题，1920×1080 会出现绿带，说明编码器严格要求 32 对齐

2. **手动旋转 YUV 数据**：
   - **问题**：在 Android 端手动旋转 YUV_420_888 或 NV12 数据时，如果处理不当会导致条纹伪影
   - **原因**：YUV 数据的 stride（行对齐）和像素对齐要求很严格，手动旋转时如果忽略 stride 或对齐要求，会导致数据错位
   - **解决方案**：在 Android 端旋转时，必须正确处理 stride 和对齐要求。当前实现中，旋转后的数据会重新排列，确保 stride 对齐（32/偶数对齐），从而避免了条纹伪影

3. **HAL 旋转与手动裁剪叠加**：
   - **问题**：同时使用 `SCALER_ROTATE_AND_CROP`（HAL 级旋转）和手动裁剪时，可能导致双重旋转/裁剪冲突
   - **现象**：横竖屏都出现条纹
   - **解决方案**：
     - 固定 `ImageAnalysis` 的 `targetRotation` 为 `Surface.ROTATION_0`
     - 停用 HAL 级旋转裁剪（注释掉 `applyRotateAndCrop`）
     - 视频旋转在 Android 端完成，通过手动旋转 YUV 数据实现

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

7. **编码器色彩格式不匹配**（**关键问题**）：
   - **问题**：某些设备（如 Pixel 6a）的硬件编码器实际使用 `COLOR_FormatYUV420Planar`（I420，分离 U/V 平面），而代码一直提供 NV12（半平面，交错 UV），导致 UV 平面错位，出现绿色/紫色条纹
   - **现象**：竖屏采集时视频画面出现绿色/紫色条纹
   - **根本原因**：编码器输入色彩格式与提供的数据格式不匹配
   - **解决方案**：
     - 检测编码器实际输入色彩格式（从 MediaCodec outputFormat 获取）
     - 如果为 Planar 格式（I420），在送入编码器前将 NV12 转换为 I420
     - 使用 `nv12ToI420()` 函数进行格式转换
     - ImageAnalysis 和 Preview 使用相同的 `targetRotation`（displayRotation），让 HAL 统一处理旋转
   - **关键代码**：`H264Encoder.encode()` 中根据 `encoderColorFormat` 动态选择 NV12 或 I420 格式

#### 当前实现的安全策略

为了避免条纹和绿带，当前代码采用了以下安全策略：

1. **安全尺寸裁剪**：
   - 4:3 比例：使用 1920×1440（1440 = 32 × 45，满足 32 对齐）
   - 16:9 比例：使用 1920×1088（1088 = 32 × 34，满足 32 对齐）
   - 不裁剪（1:1）：使用全帧，宽高分别向下对齐到 32 的倍数且为偶数（例如 1920×1920 或 4032×3008）
   - 所有尺寸均为 32 的倍数且为偶数
   - **注意**：测试发现 1920×1080 会出现绿色条带，因为 1080 不是 32 的倍数，必须使用 1088

2. **Android 端旋转处理**：
   - `ImageAnalysis` 的 `targetRotation` 固定为 `Surface.ROTATION_0`
   - 停用 HAL 级旋转裁剪
   - 视频旋转在 Android 端完成，通过手动旋转 YUV 数据实现，确保旋转后的数据满足 stride 和对齐要求
   - 发送到后端的视频已经是正确方向（rotation=0），无需后端再旋转

3. **色彩格式自适应**：
   - 检测编码器实际输入色彩格式（从 MediaCodec outputFormat 获取）
   - 如果为 `COLOR_FormatYUV420Planar`（I420），自动将 NV12 转换为 I420
   - 如果为 `COLOR_FormatYUV420SemiPlanar`（NV12），直接使用 NV12
   - 使用 `nv12ToI420()` 函数进行格式转换，确保 UV 平面正确分离

4. **严格的坐标对齐**：
   - 所有裁剪坐标和尺寸均为偶数
   - 裁剪尺寸向下对齐到 32 的倍数
   - 居中裁剪，确保坐标不越界

> **经验总结**：
> - **关键**：检测编码器实际输入色彩格式，如果为 Planar（I420），必须将 NV12 转换为 I420，否则会出现绿色/紫色条纹
> - 优先使用"安全尺寸"而非精确比例，避免与编码器 stride 冲突
> - 在 Android 端旋转时，必须正确处理 stride 和对齐要求，确保旋转后的数据满足 32/偶数对齐
> - 使用实际帧时间戳（`image.imageInfo.timestamp`）而非固定间隔，确保视频时间轴准确，FPS 可能为非整数但播放速度与现实时间完美对齐
> - 确保所有裁剪尺寸和坐标都满足对齐要求（32/偶数对齐）
> - 对齐后尺寸变化时，基于原始裁剪区域的中心点重新计算位置，保留原始裁剪意图
> - 如果遇到条纹/绿带，优先检查：
>   1. 编码器色彩格式是否匹配（Planar vs SemiPlanar）
>   2. 裁剪尺寸是否与编码器对齐要求匹配（32 的倍数且为偶数）
> - 测试时可以先使用全帧对齐（无裁剪）验证是否消除问题，再逐步缩小到目标尺寸

### 已知/已解决问题记录
- ✅ **条纹/绿带（最终解决方案）**：
  - **问题**：竖屏采集时视频画面出现绿色/紫色条纹
  - **根本原因**：编码器输入色彩格式不匹配。某些设备（如 Pixel 6a）的硬件编码器实际使用 `COLOR_FormatYUV420Planar`（I420），而代码一直提供 NV12，导致 UV 平面错位
  - **解决方案**：
    1. 检测编码器实际输入色彩格式（从 MediaCodec outputFormat 获取）
    2. 如果为 Planar 格式，在送入编码器前将 NV12 转换为 I420
    3. ImageAnalysis 和 Preview 使用相同的 `targetRotation`（displayRotation）
    4. 使用实际帧时间戳（`image.imageInfo.timestamp`）确保视频时间轴准确
  - **额外收益**：使用真实帧时间戳后，视频 FPS 反映实际捕获速率（可能为非整数），播放速度与现实时间完美对齐
- ✅ **OPPO PBBM30 条纹/绿带**：竖立/倒立时曾出现底部绿带与条纹伪影，已通过"旋转后再按目标宽高比居中裁剪并 32/偶数对齐"（`computeAlignedCropRectForRotatedFrame` + 旋转后的尺寸参与裁剪）解决，所有姿态视频已无绿带条纹。
- ⚠️ 预览 FOV 与采集 FOV 不一致（OPPO PBBM30 左/右横时采集画面更大）：预览容器为正方形，ViewPort 默认填充行为可能在横屏时对预览做了中心裁剪，而采集使用最大可用 FOV 的裁剪结果，导致采集画面比预览更大。尝试将 ViewPort scaleType 设为 FIT 效果不明显，暂未调整代码。现状：以最大 FOV 为目标，采集画面正确；预览仍可能比采集小一圈，后续需要继续排查/调优。

### 二维码识别功能

#### 功能概述

Android 采集端集成了实时二维码识别功能，用于识别用户身份并关联视频片段。

#### 技术实现

- **识别库**：ML Kit Barcode Scanning（版本 17.3.0+，支持 16KB 页面大小）
- **识别频率**：在 `ImageAnalysis` 中按 300ms 间隔采样帧进行识别，避免性能开销过大
- **识别格式**：仅识别 QR Code 格式的二维码
- **内容格式**：二维码内容应为 JSON 格式，包含 `user_id` 和 `public_key_fingerprint` 字段

#### 识别流程

1. **帧采样**：
   - 在 `ImageAnalysis` 分析器中，每隔 300ms 采样一帧进行识别
   - 使用 `qrExecutor`（单线程执行器）在后台线程进行识别，避免阻塞主线程和视频编码

2. **格式转换**：
   - 将 `ImageProxy`（YUV_420_888）转换为 NV21 格式（ML Kit 要求）
   - 使用 `toNv21ByteArray()` 扩展函数进行转换

3. **识别与解析**：
   - 使用 ML Kit 进行二维码识别
   - 如果识别成功，解析二维码内容（JSON 格式）
   - 提取 `user_id` 和 `public_key_fingerprint` 用于去重

4. **去重策略**：
   - 使用 `user_id` + `public_key_fingerprint` 作为去重键（如果存在）
   - 如果二维码不是 JSON 或缺少这些字段，使用原始内容作为去重键
   - 同一分段内，同一用户只保留置信度最高的识别结果

5. **置信度计算**：
   - 基于二维码边界框面积计算置信度
   - 面积越大，置信度越高

6. **用户反馈**：
   - **提示音**：识别成功时播放系统提示音（`ToneGenerator.TONE_PROP_ACK`，150ms）
   - **UI 提示**：在预览层显示"已识别用户"提示（带自动隐藏和节流）
   - **弱光/快速运动提示**：连续 3 次识别失败后显示"光线不足或移动过快"提示

7. **结果上报**：
   - 识别结果缓存到当前分段的去重映射中（`qrCache`）
   - 每个 MP4 分段完成后，将识别结果序列化为 JSON 数组，随分段元数据一起上报
   - 分段发送后，清空当前分段的识别结果缓存

#### 识别结果格式

每个识别结果包含以下字段：

```json
{
  "user_id": "user123",
  "public_key_fingerprint": "abc123...",
  "confidence": 0.95,
  "detected_at_ms": 1734901234567,
  "detected_at": "2025-12-23T04:14:30.123+08:00"
}
```

- `user_id`：用户 ID（从二维码 JSON 中解析，可选）
- `public_key_fingerprint`：公钥指纹（从二维码 JSON 中解析，可选）
- `confidence`：置信度（0.0-1.0，基于二维码边界框面积）
- `detected_at_ms`：检测时间戳（毫秒，绝对时间，与视频水印时间对齐）
- `detected_at`：检测时间戳（ISO 8601 格式文本）

#### 性能考虑

- **后台线程识别**：使用单线程执行器（`qrExecutor`）在后台线程进行识别，避免阻塞主线程和视频编码
- **帧采样**：按 300ms 间隔采样帧，避免每帧都进行识别
- **去重缓存**：使用 `ConcurrentHashMap` 存储当前分段的识别结果，支持并发访问
- **提示音主线程**：提示音播放切换到主线程（`viewModelScope.launch(Dispatchers.Main)`），确保音频正常播放

#### 日志记录

- 识别成功时记录日志（包含用户 ID、置信度、时间戳）
- 识别失败时记录日志（包含错误信息）
- 上传失败时记录错误日志（不重传，仅记录）

#### 16KB 页面大小兼容性

- ML Kit 17.3.0+ 已支持 16KB 页面大小对齐
- 在 `build.gradle.kts` 中设置 `packaging.jniLibs.useLegacyPackaging = false` 确保正确打包
- 使用 17.3.0 之前的版本可能会在 Android 15+ 设备上出现兼容性警告

### 视频旋转性能问题（FPS 下降）

#### 问题现象

在实际测试中发现，当设备处于不同物理方向时，录制视频的帧率差异很大：

- **设备左横（rotation 0°）**：录制视频帧率正常，可达 8 FPS 以上
- **设备其他方向（rotation 90°、180°、270°）**：录制视频帧率显著下降，仅约 2 FPS 左右

#### 问题原因

当前实现中，视频旋转采用"先旋转整个图像，再裁剪"的策略：

1. **旋转整个 1920×1920 图像**：
   - 需要处理约 370 万 Y 像素（1920 × 1920）
   - 需要处理约 185 万 UV 像素（1920 × 1920 / 2）
   - 使用嵌套循环逐像素处理，CPU 开销大

2. **内存分配开销**：
   - 需要创建完整的旋转后图像缓冲区（1920×1920）
   - 然后再从旋转后的图像中裁剪出需要的区域（如 1920×1440）

3. **性能瓶颈**：
   - 当 rotation = 0° 时，无需旋转，直接裁剪，性能正常
   - 当 rotation ≠ 0° 时，需要旋转整个图像，CPU 密集计算导致帧率下降

#### 潜在优化方案

虽然当前代码尚未实现优化，但可以考虑以下方案来提升性能：

1. **先裁剪再旋转（推荐）**：
   - 根据旋转角度计算原始图像中的裁剪区域坐标
   - 先从原始图像中裁剪出需要的区域（未旋转，如 1920×1440）
   - 只旋转这个较小的区域，而不是整个 1920×1920 图像
   - **预期效果**：可减少约 25% 的像素处理量，性能提升 2-3 倍

2. **优化循环和内存访问**：
   - 减少边界检查
   - 使用 `System.arraycopy` 替代逐像素复制
   - 预计算索引映射表

3. **并行处理 Y 和 UV 平面**：
   - 使用协程或线程池并行处理 Y 和 UV 平面

4. **使用 NDK 原生代码**：
   - 使用 C/C++ 实现旋转，通常比 Kotlin 循环快 3-5 倍
   - 但需要添加 NDK 支持，实现复杂度较高

5. **使用 OpenGL ES（GPU 加速）**：
   - 利用 GPU 进行旋转，性能最佳
   - 但实现复杂，需要管理 OpenGL 上下文

> **注意**：
> - 当前代码尚未实现上述优化，性能问题已知但暂未处理
> - 如果对帧率要求较高，建议优先使用"先裁剪再旋转"方案
> - 对于 rotation = 0° 的情况（设备左横），性能正常，不受影响

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
  - ML Kit Barcode Scanning：二维码识别（版本 17.3.0+，支持 16KB 页面大小）
  - MediaCodec：H.264 硬件编码
  - MediaMuxer：MP4 分段封装
  - OkHttp WebSocket：网络通信
- **后端**
  - Python 3.x
  - `websockets`
  - 已安装 `ffmpeg`（在服务器上可通过命令行直接执行 `ffmpeg`）
