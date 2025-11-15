# XIAO ESP32S3 WebSocket 客户端

## 功能说明

此程序让XIAO ESP32S3 Sense开发板：
- 通过WPA2 Enterprise WiFi连接到网络
- 通过WebSocket连接到服务器
- 每2秒发送一个0-100的随机整数
- 使用PIN21的LED显示连接状态

## LED状态指示

- **WiFi连接中**：快速闪烁（150ms间隔）
- **WiFi已连接，WebSocket连接中**：中速闪烁（500ms间隔）
- **全部连接成功**：每2秒闪烁一次（与发送数据同步，发送时亮100ms）
- **连接失败/断开**：常亮3秒后熄灭1秒，循环（表示需要重启）

注意：XIAO ESP32S3 Sense开发板的LED亮起需要LOW，熄灭需要HIGH。

## 配置步骤

1. 安装必要的Arduino库：
   - `WebSockets` 库（由 Markus Sattler 发布，在Arduino IDE的库管理器中搜索并安装）

2. 配置WiFi凭证和WebSocket服务器：
   - 编辑 `secrets.h` 文件
   - 将 `EAP_IDENTITY` 和 `EAP_PASSWORD` 替换为实际的WiFi凭证
   - 配置 `WEBSOCKET_SERVER` 和 `WEBSOCKET_PORT`（服务器地址和端口）

3. 上传程序到开发板：
   - 在Arduino IDE中打开 `xiao_esp32s3_websocket.ino`
   - 选择正确的开发板和端口
   - 上传程序

## 串口监视器

打开串口监视器（波特率115200）可以查看连接状态和发送的随机数。

