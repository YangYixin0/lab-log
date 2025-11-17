# 配置说明

## Arduino程序配置

在烧录Arduino程序之前，需要编辑 `arduino/xiao_esp32s3_websocket/secrets.h` 文件：

```cpp
// WiFi WPA2 Enterprise 凭证
#define EAP_IDENTITY "your_identity_here"
#define EAP_PASSWORD "your_password_here"

// WebSocket服务器地址和端口
#define WEBSOCKET_SERVER "pqzc1405495.bohrium.tech"
#define WEBSOCKET_PORT 50001
```

## 注意事项

- `secrets.h` 文件已被 `.gitignore` 忽略，不会提交到版本控制系统
- 请妥善保管WiFi凭证，不要泄露

