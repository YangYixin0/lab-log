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

1. 服务器从终端输入 `start WIDTHxHEIGHT BITRATE FPS`，向所有客户端广播 `start_capture` 命令；
2. App 收到命令后：
   - 记录服务端要求的目标分辨率 / 码率 / FPS；
   - 相机预览嵌入在主界面上半部分，预览区域宽高比自动匹配服务器要求的分辨率；
   - 使用 CameraX **ViewPort + UseCaseGroup** 确保预览（Preview）和采集（ImageAnalysis）的 FOV 完全一致，用户在预览中看到的画面就是发送到服务器的画面；
   - 在 `ImageAnalysis` 分析流中按需丢帧，并将图像编码为 H.264（无需额外裁剪，ViewPort 已统一 FOV）；
   - 通过 WebSocket 以“带自定义二进制帧头的 H.264 帧”发送给服务器；
3. 服务器端：
   - 收到 `capture_started` 状态时打开一个录制会话；
   - 按帧解出时间戳和裸 H.264 数据写文件；
   - 收到 `capture_stopped` 或连接断开时结束会话，调用 `ffmpeg` 生成 MP4。

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
  ]
}
```

服务器仅需解析其中感兴趣的分辨率即可。

### 2. 控制命令（Server → App）

服务器在终端输入：

```text
start 1600x1200 4000000 5
```

会广播给所有客户端如下 JSON：

```json
{
  "command": "start_capture",
  "payload": {
    "format": "h264",
    "resolution": { "width": 1600, "height": 1200 },
    "bitrate": 4000000,
    "fps": 5
  }
}
```

- **参数含义**
  - `format`: 当前固定为 `"h264"`。
  - `resolution`: 目标编码分辨率。App 会在 CameraX 实际输出的基础上做裁剪。
  - `bitrate`: 目标码率（bps），直接传给 `MediaFormat.KEY_BIT_RATE`。
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
  "message": "Streaming H.264 at 1600x1200 (5fps)"
}
```

- 停止推流时：

```json
{
  "status": "capture_stopped",
  "message": "Streaming has been stopped by client/server."
}
```

服务器通过这些状态来创建 / 结束录制会话，并打印友好的日志。

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

4. **相机预览与宽高比选择**
   - 授予相机权限后，预览会自动显示在主界面顶部的**正方形区域**中；
   - 预览下方有一个“宽高比”选择（目前提供 4:3 / 16:9 两种），**默认 4:3**；
   - 预览画面会以 **FIT 方式完整显示** 在正方形 Box 内，可能出现上下/左右黑边，但不会被裁剪；
   - **重要**：预览使用的宽高比与实际编码发送到服务器的视频完全一致，用户在预览中看到的取景范围就是最终录制的范围。

5. **从服务器开始录制**
   - 在 `backend/server.py` 运行的终端输入，例如：

     ```text
     # 使用 App 当前选择的宽高比（4:3 或 16:9），码率 4 MB，FPS 10
     start

     # 显式指定宽高比为 4:3，码率 4 MB，FPS 10
     start 4:3 4 10

     # 显式指定宽高比为 16:9，码率 4 MB，FPS 10
     start 16:9 4 10
     ```

   - 终端会看到类似：

     ```text
     [App Status] ... {"status":"capture_started","message":"Streaming H.264 at 1600x1200 (5fps)"}
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
     [Info]: MP4 saved to recordings/<client>_<timestamp>/stream.mp4
     ```

   - 到 `backend/recordings/` 目录下即可找到对应的 MP4 文件。

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
