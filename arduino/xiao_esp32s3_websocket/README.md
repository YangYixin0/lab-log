# XIAO ESP32S3 摄像头MJPEG WebSocket客户端

## 功能说明

此程序让XIAO ESP32S3 Sense开发板：
- 通过WPA2 Enterprise WiFi连接到网络
- 初始化OV3660摄像头（UXGA分辨率，1600×1200）
- 通过WebSocket实时发送摄像头MJPEG数据（JPEG二进制）
- 支持通过WebSocket接收控制命令（start/stop/status）
- 使用PIN21的LED显示连接状态

## 摄像头配置

- **分辨率**：UXGA (1600×1200)
- **格式**：JPEG
- **帧缓冲区**：使用PSRAM存储
- **JPEG质量**：12（1-63，越小质量越高）
- **帧率**：不控制，尽可能快发送

## LED状态指示

- **WiFi连接中**：闪烁（500ms间隔）
- **WebSocket连接中**：闪烁（500ms间隔）
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

- `start` - 开始采集和上传摄像头数据
- `stop` - 停止采集和上传
- `status` - 查询当前状态

Arduino会通过WebSocket发送确认消息，并在串口监视器中显示状态。

## 串口监视器

打开串口监视器（波特率115200）可以查看：
- 摄像头初始化状态
- WiFi连接状态
- WebSocket连接状态
- 接收到的控制命令
- 采集状态变化
- 发送帧的状态（可选）

## 文件说明

- `xiao_esp32s3_websocket.ino` - 主程序文件
- `secrets.h` - WiFi和WebSocket服务器配置（不提交到版本控制）
- `camera_pins.h` - XIAO ESP32S3摄像头引脚定义

## 注意事项

### Brownout检测器问题

**重要**：本程序**不使用**禁用Brownout检测器的代码（如 `WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0)`）。

**原因**：在ESP32-S3上，尝试禁用Brownout检测器反而可能导致Brownout重启循环。