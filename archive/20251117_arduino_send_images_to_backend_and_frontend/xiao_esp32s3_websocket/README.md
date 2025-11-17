# XIAO ESP32S3 摄像头MJPEG WebSocket客户端

## 功能说明

此程序让XIAO ESP32S3 Sense开发板：
- 通过WPA2 Enterprise WiFi连接到网络
- 初始化OV3660摄像头（HD分辨率，1280×720）
- 通过WebSocket实时发送摄像头MJPEG数据（JPEG二进制）
- 支持通过WebSocket接收控制命令（start/stop/status）
- 使用PIN21的LED显示连接状态

## 摄像头配置

- **分辨率**：HD (1280×720)
- **格式**：JPEG
- **帧缓冲区**：使用PSRAM存储
- **JPEG质量**：12（1-63，越小质量越高）
- **帧率**：不控制，尽可能快发送
- **图像翻转**：已启用垂直翻转（上下翻转），修正摄像头安装方向导致的图像颠倒问题

## LED状态指示

- **WiFi连接中**：闪烁（200ms间隔）
- **WebSocket连接中**：闪烁（200ms间隔）
- **连接成功且采集中**：常亮
- **连接成功但未采集**：每3秒亮300ms
- **连接失败/断开（ERROR）**：每6秒亮300ms

注意：XIAO ESP32S3 Sense开发板的LED亮起需要LOW，熄灭需要HIGH。

## 配置步骤

1. 安装必要的Arduino库：
   - `WebSockets` 库（由 Markus Sattler 发布，在Arduino IDE的库管理器中搜索并安装）
   - ESP32摄像头库已包含在ESP32 Arduino Core（esp32 by Espressif Systems）中

2. 配置WiFi凭证和WebSocket服务器：
   - 编辑 `secrets.h` 文件
   - 将 `EAP_IDENTITY` 和 `EAP_PASSWORD` 替换为实际的WiFi凭证
   - 配置 `WEBSOCKET_SERVER` 和 `WEBSOCKET_PORT`（服务器地址和端口，路径固定为 `/esp`）

3. 上传程序到开发板：
   - 在Arduino IDE中打开 `xiao_esp32s3_websocket.ino`
   - 选择开发板：XIAO_ESP32S3
   - 选择正确的端口
   - 上传程序

## 控制命令

连接WebSocket后，默认不开始采集。需要通过服务器发送命令控制：

### start 命令

开始采集和上传摄像头数据，支持可选的分辨率和JPEG质量参数：

- `start` - 使用默认参数（HD分辨率，质量12）
- `start <resolution>` - 指定分辨率，使用默认质量（12）
- `start <resolution> <quality>` - 指定分辨率和质量

**支持的分辨率：**
- `QQVGA` - 160×120
- `QCIF` - 176×144
- `HQVGA` - 240×176
- `240X240` - 240×240
- `QVGA` - 320×240
- `CIF` - 400×296
- `HVGA` - 480×320
- `VGA` - 640×480
- `SVGA` - 800×600
- `XGA` - 1024×768
- `HD` - 1280×720（默认）
- `SXGA` - 1280×1024
- `UXGA` - 1600×1200
- `FHD` - 1920×1080
- `P_HD` - 720×1280
- `P_3MP` - 864×1536
- `QXGA` - 2048×1536
- `QSXGA` - 2560×1920

**注意：** 某些高分辨率（如QXGA、QSXGA）可能不被所有摄像头模块支持，请根据实际硬件选择合适的分辨率。

**JPEG质量：**
- 范围：1-63（越小质量越高，默认12）

**示例：**
- `start` - 使用默认参数（HD, 12）
- `start HD` - 使用HD分辨率（1280×720），质量12
- `start FHD 8` - 使用FHD分辨率（1920×1080），质量8

### 其他命令

- `stop` - 停止采集和上传
- `status` - 查询当前状态

Arduino会通过WebSocket发送确认消息（包含实际使用的参数），并在串口监视器中显示状态。

## 串口监视器

打开串口监视器（波特率115200）可以查看：
- 摄像头初始化状态
- WiFi连接状态
- WebSocket连接状态
- 接收到的控制命令
- 采集状态变化
- 发送帧的状态（可选）

## 代码结构

代码使用C++命名空间组织，提高可读性和可维护性，同时保持过程式编程的性能优势：

### `Camera` 命名空间
- `init()` - 初始化摄像头（包含图像垂直翻转设置）
- `sendFrame()` - 发送摄像头帧到WebSocket
- `isCapturing` - 采集状态变量

### `WiFiManager` 命名空间
- `connect()` - 连接WPA2 Enterprise WiFi
- `isConnected()` - 检查WiFi连接状态
- `reconnect()` - 重连WiFi

### `WebSocketManager` 命名空间
- `connect()` - 连接WebSocket服务器
- `eventHandler()` - 处理WebSocket事件（连接、断开、命令等）
- `isConnected()` - 检查WebSocket连接状态
- `loop()` - 处理WebSocket事件循环
- `reconnect()` - 重连WebSocket
- `webSocket` - WebSocket客户端实例

### `StatusLED` 命名空间
- `init()` - 初始化LED引脚
- `update()` - 根据连接状态更新LED显示
- 相关状态变量（`PIN`, `lastUpdate`, `lastErrorCycle`）

### 全局变量
- `ConnectionState` 枚举类 - 连接状态枚举，用于表示设备所处的连接状态（如未连接、WiFi已连接、WebSocket已连接、正在采集等），用于判断和切换设备各个网络阶段。
- `currentState` - 当前连接状态，是`ConnectionState`枚举类的变量。

### 命名空间优势
- **代码组织**：相关功能逻辑分组，提高可读性
- **无性能开销**：命名空间不增加内存或执行时间
- **避免命名冲突**：不同模块的变量和函数不会冲突
- **易于维护**：功能模块化，便于修改和扩展

## 文件说明

- `xiao_esp32s3_websocket.ino` - 主程序文件
- `secrets.h` - WiFi和WebSocket服务器配置（不提交到版本控制）
- `camera_pins.h` - XIAO ESP32S3摄像头引脚定义

## 注意事项

### Brownout检测器问题

**重要**：本程序**不使用**禁用Brownout检测器的代码（如 `WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0)`）。

**原因**：在ESP32-S3上，尝试禁用Brownout检测器反而可能导致Brownout重启循环。