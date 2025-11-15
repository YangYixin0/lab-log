# WebSocket 服务器

## 功能说明

此Python WebSocket服务器：
- 监听 `0.0.0.0:50001` 端口
- 接收ESP32发送的随机数
- 在终端打印接收到的数据（包含时间戳和客户端信息）

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行服务器

```bash
python server.py
```

服务器启动后会显示监听地址，并等待客户端连接。当ESP32连接并发送数据时，会在终端打印接收到的随机数。

## 停止服务器

按 `Ctrl+C` 停止服务器。

