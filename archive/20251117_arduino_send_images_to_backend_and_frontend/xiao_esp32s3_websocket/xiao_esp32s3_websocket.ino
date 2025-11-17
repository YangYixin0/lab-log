/*
 * 功能描述：XIAO ESP32S3 Sense连接WPA2 Enterprise WiFi，通过WebSocket发送摄像头MJPEG数据
 *           使用PIN21的LED显示连接状态
 *           使用命名空间组织代码，添加图像垂直翻转功能
 */
#include <WiFi.h>               // 用于基础的WiFi连接

#if __has_include("esp_eap_client.h")
#include "esp_eap_client.h"     // WPA2 Enterprise 认证
#else
#include "esp_wpa2.h"           // esp_eap_client.h的旧版本
#endif

#include "esp_camera.h"          // ESP32摄像头库

#include "secrets.h"
const char *ssid = "eduroam";   // 网络SSID号

#include <WebSocketsClient.h>   // WebSocket客户端库

// WebSocket配置（从secrets.h读取）
const char *websocket_server = WEBSOCKET_SERVER;
const int websocket_port = WEBSOCKET_PORT;
const char *websocket_path = "/esp";

// 摄像头配置
#define CAMERA_MODEL_XIAO_ESP32S3 // Has PSRAM
#include "camera_pins.h"

// 状态枚举（全局，多个命名空间需要访问）
enum ConnectionState {
  STATE_WIFI_CONNECTING,      // WiFi连接中
  STATE_WEBSOCKET_CONNECTING, // WebSocket连接中
  STATE_CONNECTED,            // 全部连接成功
  STATE_ERROR                 // 连接失败/断开
};

// 全局状态变量（多个命名空间需要访问）
ConnectionState currentState = STATE_WIFI_CONNECTING;

// ==================== Camera 命名空间 ====================
namespace Camera {
  bool isCapturing = false;  // 是否正在采集和上传
  
  void init() {
    Serial.println("初始化摄像头...");
    
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sscb_sda = SIOD_GPIO_NUM;
    config.pin_sscb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.frame_size = FRAMESIZE_HD;      // 1280×720
    config.pixel_format = PIXFORMAT_JPEG;     // JPEG格式用于流传输
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    config.fb_location = CAMERA_FB_IN_PSRAM; // 使用PSRAM存储帧缓冲区
    config.jpeg_quality = 12;                  // JPEG质量（1-63，越小质量越高）
    config.fb_count = 1;
    
    // 初始化摄像头
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
      Serial.printf("摄像头初始化失败，错误代码: 0x%x\n", err);
      Serial.println("请检查摄像头连接");
      return;
    }
    
    // 设置图像垂直翻转（上下翻转）
    sensor_t *s = esp_camera_sensor_get();
    if (s != NULL) {
      s->set_vflip(s, 1);  // 垂直翻转（上下翻转）
      Serial.println("已启用图像垂直翻转");
    }
    
    Serial.println("摄像头初始化成功");
    Serial.printf("分辨率: UXGA (1600×1200)\n");
    Serial.printf("格式: JPEG\n");
    Serial.printf("使用PSRAM: 是\n");
  }
  
  void sendFrame(WebSocketsClient& ws) {
    if (currentState == STATE_CONNECTED && ws.isConnected() && isCapturing) {
      // 捕获摄像头帧
      camera_fb_t * fb = esp_camera_fb_get();
      if (!fb) {
        Serial.println("摄像头捕获失败");
        return;
      }
      
      // 通过WebSocket发送JPEG二进制数据
      if (ws.sendBIN(fb->buf, fb->len)) {
        // 发送成功（可选：打印帧大小）
        // Serial.printf("发送帧: %u 字节\n", fb->len);
      } else {
        Serial.println("WebSocket发送失败");
      }
      
      // 释放帧缓冲区
      esp_camera_fb_return(fb);
    }
  }
  
  bool setResolution(String resolution) {
    sensor_t *s = esp_camera_sensor_get();
    if (s == NULL) {
      Serial.println("无法获取传感器对象");
      return false;
    }
    
    resolution.toUpperCase();
    framesize_t framesize = FRAMESIZE_UXGA;  // 默认值
    String resolutionName = "HD";
    
    if (resolution == "QQVGA") {
      framesize = FRAMESIZE_QQVGA;
      resolutionName = "QQVGA (160×120)";
    } else if (resolution == "QCIF") {
      framesize = FRAMESIZE_QCIF;
      resolutionName = "QCIF (176×144)";
    } else if (resolution == "HQVGA") {
      framesize = FRAMESIZE_HQVGA;
      resolutionName = "HQVGA (240×176)";
    } else if (resolution == "240X240") {
      framesize = FRAMESIZE_240X240;
      resolutionName = "240X240 (240×240)";
    } else if (resolution == "QVGA") {
      framesize = FRAMESIZE_QVGA;
      resolutionName = "QVGA (320×240)";
    } else if (resolution == "CIF") {
      framesize = FRAMESIZE_CIF;
      resolutionName = "CIF (400×296)";
    } else if (resolution == "HVGA") {
      framesize = FRAMESIZE_HVGA;
      resolutionName = "HVGA (480×320)";
    } else if (resolution == "VGA") {
      framesize = FRAMESIZE_VGA;
      resolutionName = "VGA (640×480)";
    } else if (resolution == "SVGA") {
      framesize = FRAMESIZE_SVGA;
      resolutionName = "SVGA (800×600)";
    } else if (resolution == "XGA") {
      framesize = FRAMESIZE_XGA;
      resolutionName = "XGA (1024×768)";
    } else if (resolution == "HD") {
      framesize = FRAMESIZE_HD;
      resolutionName = "HD (1280×720)";
    } else if (resolution == "SXGA") {
      framesize = FRAMESIZE_SXGA;
      resolutionName = "SXGA (1280×1024)";
    } else if (resolution == "UXGA") {
      framesize = FRAMESIZE_UXGA;
      resolutionName = "UXGA (1600×1200)";
    } else if (resolution == "FHD") {
      framesize = FRAMESIZE_FHD;
      resolutionName = "FHD (1920×1080)";
    } else if (resolution == "P_HD") {
      framesize = FRAMESIZE_P_HD;
      resolutionName = "P_HD (720×1280)";
    } else if (resolution == "P_3MP") {
      framesize = FRAMESIZE_P_3MP;
      resolutionName = "P_3MP (864×1536)";
    } else if (resolution == "QXGA") {
      framesize = FRAMESIZE_QXGA;
      resolutionName = "QXGA (2048×1536)";
    // } else if (resolution == "QSXGA") {
    //   framesize = FRAMESIZE_QSXGA;
    //   resolutionName = "QSXGA (2560×1920)";  // OV3660不支持
    } else {
      Serial.printf("未知分辨率: %s，使用默认值 UXGA\n", resolution.c_str());
    }
    
    s->set_framesize(s, framesize);
    Serial.printf("分辨率已设置为: %s\n", resolutionName.c_str());
    return true;
  }
  
  bool setQuality(int quality) {
    if (quality < 1 || quality > 63) {
      Serial.printf("JPEG质量超出范围 (1-63): %d，使用默认值 12\n", quality);
      quality = 12;
    }
    
    sensor_t *s = esp_camera_sensor_get();
    if (s == NULL) {
      Serial.println("无法获取传感器对象");
      return false;
    }
    
    s->set_quality(s, quality);
    Serial.printf("JPEG质量已设置为: %d (1-63，越小质量越高)\n", quality);
    return true;
  }
}

// ==================== WiFiManager 命名空间 ====================
namespace WiFiManager {
  void connect() {
    Serial.println();
    Serial.print("尝试连接WiFi: ");
    Serial.println(ssid);
    
    currentState = STATE_WIFI_CONNECTING;
    
    WiFi.disconnect(true);
    WiFi.mode(WIFI_STA);
    
    #if __has_include("esp_eap_client.h")
      Serial.println("使用 esp_eap_client.h");
      esp_eap_client_set_identity((uint8_t *)EAP_IDENTITY, strlen(EAP_IDENTITY));
      esp_eap_client_set_username((uint8_t *)EAP_IDENTITY, strlen(EAP_IDENTITY));
      esp_eap_client_set_password((uint8_t *)EAP_PASSWORD, strlen(EAP_PASSWORD));
      esp_wifi_sta_enterprise_enable();
    #else
      Serial.println("使用 esp_wpa2.h");
      esp_wifi_sta_wpa2_ent_set_identity((uint8_t *)EAP_IDENTITY, strlen(EAP_IDENTITY));
      esp_wifi_sta_wpa2_ent_set_username((uint8_t *)EAP_IDENTITY, strlen(EAP_IDENTITY));
      esp_wifi_sta_wpa2_ent_set_password((uint8_t *)EAP_PASSWORD, strlen(EAP_PASSWORD));
      esp_wifi_sta_wpa2_ent_enable();
    #endif
    
    WiFi.begin(ssid);
    int time_establishing_connection = 0;
    while (WiFi.status() != WL_CONNECTED) {
      delay(100);
      Serial.print(".");
      time_establishing_connection++;
      if (time_establishing_connection >= 900) {  // 90秒超时
        Serial.println();
        Serial.println("WiFi连接超时，重启开发板...");
        ESP.restart();
      }
    }
    
    Serial.println();
    Serial.print("WiFi已连接，本地IP: ");
    Serial.println(WiFi.localIP());
  }
  
  bool isConnected() {
    return WiFi.status() == WL_CONNECTED;
  }
  
  void reconnect() {
    Serial.println("WiFi连接丢失，尝试重连...");
    currentState = STATE_WIFI_CONNECTING;
    connect();
  }
}

// ==================== WebSocketManager 命名空间 ====================
namespace WebSocketManager {
  WebSocketsClient webSocket;
  
  void eventHandler(WStype_t type, uint8_t * payload, size_t length) {
    switch(type) {
      case WStype_DISCONNECTED:
        Serial.println("WebSocket断开连接");
        currentState = STATE_ERROR;
        break;
        
      case WStype_CONNECTED:
        Serial.print("WebSocket已连接: ");
        Serial.println((char*)payload);
        currentState = STATE_CONNECTED;
        Serial.println("等待开始采集命令...");
        Serial.println("可用命令: start [分辨率] [质量], stop, status");
        Serial.println("  示例: start, start UXGA, start UXGA 12, start VGA 15");
        Camera::isCapturing = false;  // 连接后默认不采集
        break;
        
      case WStype_TEXT:
        {
          String command = String((char*)payload);
          command.trim();
          String commandLower = command;
          commandLower.toLowerCase();
          
          Serial.print("收到命令: ");
          Serial.println(command);
          
          if (commandLower.startsWith("start")) {
            // 如果正在采集，先停止采集
            if (Camera::isCapturing) {
              Camera::isCapturing = false;
              Serial.println(">>> 停止当前采集，准备重新开始");
            }
            
            // 解析参数（分辨率和质量）
            String resolution = "UXGA";  // 默认分辨率
            int quality = 12;            // 默认质量
            
            // 解析参数：start <resolution> <quality>
            int firstSpace = command.indexOf(' ');
            if (firstSpace > 0) {
              int secondSpace = command.indexOf(' ', firstSpace + 1);
              if (secondSpace > firstSpace) {
                // 有两个参数：分辨率和质量
                resolution = command.substring(firstSpace + 1, secondSpace);
                quality = command.substring(secondSpace + 1).toInt();
              } else {
                // 只有一个参数：可能是分辨率或质量
                String param = command.substring(firstSpace + 1);
                // 尝试解析为数字（质量）
                int paramInt = param.toInt();
                if (paramInt > 0 && paramInt <= 63) {
                  // 是质量参数
                  quality = paramInt;
                } else {
                  // 是分辨率参数
                  resolution = param;
                }
              }
            }
            
            // 设置摄像头参数
            Camera::setResolution(resolution);
            Camera::setQuality(quality);
            
            // 开始采集（或重新开始采集）
            Camera::isCapturing = true;
            Serial.println(">>> 开始采集和上传摄像头数据");
            // 发送确认消息，包含使用的参数
            String ackMsg = "ACK: 开始采集 (分辨率: " + resolution + ", 质量: " + String(quality) + ")";
            webSocket.sendTXT(ackMsg);
          }
          else if (commandLower == "stop") {
            if (Camera::isCapturing) {
              Camera::isCapturing = false;
              Serial.println(">>> 停止采集和上传");
              // 发送确认消息
              webSocket.sendTXT("ACK: 停止采集");
            } else {
              Serial.println(">>> 当前未在采集");
              webSocket.sendTXT("ACK: 未在采集");
            }
          }
          else if (commandLower == "status") {
            String status = Camera::isCapturing ? "采集中" : "已停止";
            Serial.printf(">>> 当前状态: %s\n", status.c_str());
            webSocket.sendTXT("STATUS: " + status);
          }
          else {
            Serial.println(">>> 未知命令，可用命令: start, stop, status");
            webSocket.sendTXT("ERROR: 未知命令");
          }
        }
        break;
        
      case WStype_BIN:
        Serial.print("收到二进制数据，长度: ");
        Serial.println(length);
        break;
        
      case WStype_ERROR:
        Serial.print("WebSocket错误: ");
        Serial.println((char*)payload);
        currentState = STATE_ERROR;
        break;
        
      default:
        break;
    }
  }
  
  void connect() {
    currentState = STATE_WEBSOCKET_CONNECTING;
    
    Serial.print("尝试连接WebSocket服务器: ");
    Serial.print(websocket_server);
    Serial.print(":");
    Serial.println(websocket_port);
    
    // 设置WebSocket事件处理
    webSocket.begin(websocket_server, websocket_port, websocket_path);
    webSocket.onEvent(eventHandler);
    webSocket.setReconnectInterval(5000);  // 5秒重连间隔
  }
  
  bool isConnected() {
    return webSocket.isConnected();
  }
  
  void loop() {
    webSocket.loop();
  }
  
  void reconnect() {
    Serial.println("WebSocket连接失败，尝试重连...");
    connect();
  }
}

// ==================== StatusLED 命名空间 ====================
namespace StatusLED {
  const int PIN = 21;
  static unsigned long lastUpdate = 0;
  static unsigned long lastErrorCycle = 0;
  
  void init() {
    pinMode(PIN, OUTPUT);
    digitalWrite(PIN, HIGH);  // XIAO ESP32S3 LED熄灭需要HIGH
  }
  
  void update() {
    unsigned long currentTime = millis();
    
    switch(currentState) {
      case STATE_WIFI_CONNECTING:
        // 闪烁（200ms间隔）
        if (currentTime - lastUpdate >= 200) {
          digitalWrite(PIN, !digitalRead(PIN));
          lastUpdate = currentTime;
        }
        break;
        
      case STATE_WEBSOCKET_CONNECTING:
        // 闪烁（200ms间隔）
        if (currentTime - lastUpdate >= 200) {
          digitalWrite(PIN, !digitalRead(PIN));
          lastUpdate = currentTime;
        }
        break;
        
      case STATE_CONNECTED:
        if (Camera::isCapturing) {
          // 采集中：常亮
          digitalWrite(PIN, LOW);  // LED亮
        } else {
          // 未采集：每3秒亮300ms
          unsigned long cycleTime = (currentTime - lastUpdate) % 3000;
          if (cycleTime < 300) {
            digitalWrite(PIN, LOW);  // LED亮
          } else {
            digitalWrite(PIN, HIGH); // LED灭
          }
          // 更新lastUpdate以保持周期
          if (currentTime - lastUpdate >= 3000) {
            lastUpdate = currentTime;
          }
        }
        break;
        
      case STATE_ERROR:
        {
          // 每6秒亮300ms
          unsigned long errorCycleTime = (currentTime - lastErrorCycle) % 6000;
          if (errorCycleTime < 300) {
            digitalWrite(PIN, LOW);  // LED亮
          } else {
            digitalWrite(PIN, HIGH); // LED灭
          }
          // 更新lastErrorCycle以保持周期
          if (currentTime - lastErrorCycle >= 6000) {
            lastErrorCycle = currentTime;
          }
        }
        break;
    }
  }
}

// ==================== 主程序 ====================
void setup() {
  // 初始化串口
  Serial.begin(115200);
  delay(1000);
  
  // 初始化LED
  StatusLED::init();
  
  Serial.println();
  Serial.println("=== XIAO ESP32S3 Camera WebSocket Client ===");
  
  // 初始化摄像头
  Camera::init();
  
  // 建立WiFi连接
  WiFiManager::connect();
  
  // 建立WebSocket连接
  WebSocketManager::connect();
}

void checkConnections() {
  // 检查WiFi连接
  if (!WiFiManager::isConnected()) {
    WiFiManager::reconnect();
    WebSocketManager::reconnect();
    return;
  }
  
  // 检查WebSocket连接
  if (currentState != STATE_CONNECTED && currentState != STATE_WEBSOCKET_CONNECTING) {
    if (currentState == STATE_ERROR) {
      WebSocketManager::reconnect();
    }
  }
}

void loop() {
  // 更新LED状态
  StatusLED::update();
  
  // 处理WebSocket事件
  WebSocketManager::loop();
  
  // 检查连接状态
  checkConnections();
  
  // 如果连接成功且正在采集，持续发送摄像头帧
  if (currentState == STATE_CONNECTED && WebSocketManager::isConnected() && Camera::isCapturing) {
    Camera::sendFrame(WebSocketManager::webSocket);
    // 不添加延迟，尽可能快地发送帧
  }
  
  delay(10);  // 短暂延迟，避免CPU占用过高
}
