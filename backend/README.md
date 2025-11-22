# 后端服务器（Android 相机推流）

本目录下的 `server.py` 是一个针对 Android 相机 App 的 WebSocket 服务器，  
负责接收来自手机的 H.264 视频帧，按会话写入磁盘，并在录制结束后封装成 MP4 文件。

---

## 核心功能

- **监听地址**：`ws://0.0.0.0:50001`
- **客户端类型**：Android 相机 App（见 `android-camera/`）
- **数据流处理**：
  - 接收 App 通过 WebSocket 发送的二进制帧：自定义 16 字节帧头 + H.264 裸码流；
  - 每个客户端、每个会话独立落盘到 `recordings/<client>_<timestamp>/`；
  - 结束时调用 `ffmpeg` 将 `stream.h264` 封装为 `stream.mp4`。
- **控制命令**：
  - 在服务器终端输入 `start` / `stop` 控制所有已连接客户端；
  - `start` 命令可携带分辨率、码率和期望 FPS，传递给 App。
- **时间与 FPS 估算**：
  - App 在帧头中写入设备侧时间戳（毫秒）；
  - 服务器同时记录服务器到达时间；
  - 录制结束后，通过时间跨度估算实际 FPS，传递给 `ffmpeg`，避免时间轴错误。

---

## 目录结构

- `server.py`：主服务器脚本（WebSocket + 录制逻辑）。
- `requirements.txt`：Python 依赖，仅包含 `websockets`。
- `recordings/`：录制输出目录（自动创建），每个会话一个子目录：
  - `stream.h264`：裸 H.264 码流；
  - `stream.mp4`：封装好的 MP4 文件。

---

## 主要组件说明

### 1. 自定义帧头与解析

服务器与 Android App 约定每个二进制消息格式为：

```text
8 字节  int64  timestampMs  设备时间戳（毫秒）
4 字节  int32  frameSeq     帧序号（低 32 位递增）
4 字节  int32  payloadSize  后续 H.264 数据长度
N 字节  bytes  payload      H.264 裸码流
```

在 `server.py` 中：

- **常量**
  - `FRAME_HEADER_FORMAT = ">QII"`：使用 `struct` 以大端解析帧头。
  - `FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)`：帧头总长度 16 字节。
- **`parse_frame_packet(packet: bytes)`**
  - 检查长度是否至少包含帧头；
  - 按 `FRAME_HEADER_FORMAT` 解出 `timestamp_ms`、`frame_seq`、`payload_length`；
  - 截取后续负载并校验长度；
  - 返回 `(timestamp_ms, frame_seq, payload)`。

### 2. 录制会话 `RecordingSession`

位于 `server.py` 顶部附近：

- 创建：
  - 每当收到 App 的 `capture_started` 状态时，通过 `start_recording()` 创建新会话。
  - 会在 `recordings/` 下创建形如 `IP_PORT_YYYYMMDD_HHMMSS/` 的目录。
  - 打开 `stream.h264` 以二进制方式写入。
- 字段：
  - `client_id`：`"<ip>_<port>"`，用作录制目录前缀。
  - `session_dir` / `raw_path` / `mp4_path`：会话目录与文件路径。
  - `frame_count`：累计帧数。
  - `first_device_ts_ms` / `last_device_ts_ms`：首尾设备时间戳（毫秒）。
  - `first_arrival_ms` / `last_arrival_ms`：首尾服务器到达时间（毫秒）。
- 方法：
  - `add_frame(timestamp_ms, arrival_ms, payload)`：
    - 将 `payload` 追加写入 `stream.h264`；
    - 更新帧数与时间戳范围。
  - `finalize()`：
    - 先关闭文件；
    - 调用 `_determine_fps()` 估算 FPS；
    - 调用 `mux_frames_to_mp4()` 生成 MP4；返回 MP4 路径（或 `None`）。
  - `_determine_fps()`：
    - 内部通过 `frame_count / duration_seconds` 计算 FPS；
    - 分别基于设备时间戳和服务器到达时间算两个值；
    - 优先选取“服务器到达时间”估算结果，且要求 > 1.5fps 才认为可信；
    - 否则回退到“设备时间戳”估算结果；
    - 两者都不可用时，回退到保底 `10.0` FPS。

### 3. 裸流封装 `mux_frames_to_mp4`

函数签名：

```python
def mux_frames_to_mp4(raw_path: Path, output_path: Path, fps: float) -> Optional[Path]:
```

逻辑：

- 若裸流文件不存在则跳过，打印警告。
- 使用 `subprocess.run` 调用 `ffmpeg`：

```bash
ffmpeg -y -f h264 -r <fps> -i stream.h264 -c:v copy stream.mp4
```

- `-f h264`：告诉 ffmpeg 输入是裸 H.264；
- `-r <fps>`：显式指定帧率，避免 ffmpeg 从码流错误推断导致“1fps 视频”；
- `-c:v copy`：不重编码，只做封装，速度快且无损。
- 若 `ffmpeg` 返回码非 0，会打印 stderr 并返回 `None`。

> 注意：需要在服务器环境安装 `ffmpeg`，并确保命令行中可直接调用。  
> 也可以通过设置环境变量 `FFMPEG_BIN=/path/to/ffmpeg` 指定自定义路径。

### 4. WebSocket 处理流程

#### 4.1 连接入口 `connection_handler(websocket)`

- 为每个新连接：
  - 计算 `client_id = "<ip>_<port>"`；
  - 通过 `websocket.request.path` 记录请求路径（目前仅作日志用途）；
  - 将连接加入全局集合 `CONNECTED_CLIENTS`。
- 然后调用 `consumer_handler(websocket)` 处理消息。

#### 4.2 消息处理 `consumer_handler(websocket)`

主要逻辑：

- 文本消息（`str`）：
  - 认为是 App 上报的 JSON 状态，例如：

    ```json
    { "status": "capture_started", "message": "..." }
    ```

  - 解析 `status` 字段：
    - `capture_started`：调用 `start_recording(websocket, client_id)`。
    - `capture_stopped`：调用 `finalize_recording(websocket, client_id)`。
  - 解析失败则直接忽略（兼容其他日志或调试输出）。

- 二进制消息（`bytes`）：
  - 必须在存在活动 `RecordingSession` 的前提下处理；
  - 使用 `parse_frame_packet()` 解析帧头和负载；
  - 打印帧日志：

    ```text
    [Frame]: <client_id> seq=<n> timestamp=<ms>ms size=<bytes> bytes
    ```

  - 使用 `asyncio.get_running_loop().time()` 获取当前服务器时间（秒），转换为毫秒；
  - 调用 `session.add_frame(timestamp_ms, arrival_ms, payload)` 追加记录。

- 连接异常或关闭时：
  - 捕获 `websockets.exceptions.ConnectionClosed`；
  - 调用 `finalize_recording()` 确保会话结束并尝试生成 MP4；
  - 将客户端从 `CONNECTED_CLIENTS` 移除。

---

## 终端控制命令

由 `terminal_input_handler()` 实现，服务器启动后会在终端打印提示：

```text
Enter command ('start [w]x[h] [bitrate] [fps]' or 'stop'):
> 
```

支持的命令：

- **`start [w]x[h] [bitrate] [fps]`**
  - `w` / `h`：目标分辨率，必填，例如 `1600x1200`、`1920x1080`。
  - `bitrate`：可选，单位 bps，默认 `4000000`（约 4Mbps）。
  - `fps`：可选，目标帧率：
    - 默认 `10`；
    - 负数会被修正为 `0`；
    - `0` 表示“不限帧率”，App 会尽可能多地发送帧（仅受硬件与网络限制）。
  - 示例：

    ```text
    start 1600x1200 4000000 5
    start 1920x1080 4000000 0
    ```

  - 内部会转换为 JSON：

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

  - 并通过 `broadcast()` 广播给所有 `CONNECTED_CLIENTS`。

- **`stop`**
  - 广播 `{ "command": "stop_capture" }`；
  - App 收到后会停止推流，并上报 `capture_stopped` 状态；
  - 服务器在 `consumer_handler` 中捕捉到状态后调用 `finalize_recording()` 完成本次录制。

其他字符串会被认为是未知命令，只在终端打印错误提示，不发送给客户端。

---

## 运行步骤

1. **安装依赖**

   在 `backend/` 目录：

   ```bash
   pip install -r requirements.txt
   ```

   确保系统中已安装 `ffmpeg` 。如果未安装，在 Ubuntu/Debian 中可以通过 apt 安装：

   ```bash
   sudo apt update
   sudo apt install ffmpeg
   ffmpeg -version
   ```

2. **启动服务器**

   ```bash
   python server.py
   ```

   看到类似输出：

   ```text
   WebSocket server started at ws://0.0.0.0:50001
   You can now connect your Android Camera App.
   Enter command ('start [w]x[h] [bitrate] [fps]' or 'stop'):
   >
   ```

3. **连接 Android 相机 App**

   - 在手机端 App 中将 URL 设置为：

     ```text
     ws://<server_host>:50001/android-cam
     ```

   - 连接成功后，服务器终端会打印 `[Connection]` 日志。

4. **开始与停止录制**

   - 在服务器终端输入 `start ...` 开始采集；
   - 输入 `stop` 停止采集并生成 MP4。

5. **查看录制结果**

   - 在 `backend/recordings/` 目录中找到形如：

     ```text
     <ip>_<port>_YYYYMMDD_HHMMSS/stream.mp4
     ```

   - 使用任意播放器打开验证帧率、分辨率与时长。

---

## 依赖与环境要求

- Python 3.x
- `websockets`
- `ffmpeg`（系统级工具，非 Python 依赖）

可选环境变量：

- `FFMPEG_BIN`：指定 ffmpeg 可执行文件的路径，例如：

```bash
export FFMPEG_BIN=/usr/local/bin/ffmpeg
```
