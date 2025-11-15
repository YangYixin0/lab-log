/*
 * 功能描述：XIAO ESP32S3 Sense连接WPA2 Enterprise WiFi，通过WebSocket发送摄像头MJPEG数据
 *           使用PIN21的LED显示连接状态
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
const char *websocket_path = "/";

// 摄像头配置
#define CAMERA_MODEL_XIAO_ESP32S3 // Has PSRAM
#include "camera_pins.h"

// LED配置
const int LED_PIN = 21;

// 状态枚举
enum ConnectionState {
  STATE_WIFI_CONNECTING,      // WiFi连接中
  STATE_WEBSOCKET_CONNECTING, // WebSocket连接中
  STATE_CONNECTED,            // 全部连接成功
  STATE_ERROR                 // 连接失败/断开
};

ConnectionState currentState = STATE_WIFI_CONNECTING;

// WebSocket客户端实例
WebSocketsClient webSocket;

// LED状态控制变量
unsigned long lastLedUpdate = 0;
unsigned long lastErrorCycle = 0;
bool errorLedState = false;

// 采集控制变量
bool isCapturing = false;  // 是否正在采集和上传

void setup() {
  // 初始化串口
  Serial.begin(115200);
  delay(1000);
  
  // 初始化LED
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // XIAO ESP32S3 LED熄灭需要HIGH
  
  Serial.println();
  Serial.println("=== XIAO ESP32S3 Camera WebSocket Client ===");
  
  // 初始化摄像头
  initCamera();
  
  // 建立WiFi连接
  connectWiFi();
  
  // 建立WebSocket连接
  connectWebSocket();
}

void initCamera() {
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
  config.frame_size = FRAMESIZE_UXGA;      // 1600×1200
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
  
  Serial.println("摄像头初始化成功");
  Serial.printf("分辨率: UXGA (1600×1200)\n");
  Serial.printf("格式: JPEG\n");
  Serial.printf("使用PSRAM: 是\n");
}

void connectWiFi() {
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

void connectWebSocket() {
  currentState = STATE_WEBSOCKET_CONNECTING;
  
  Serial.print("尝试连接WebSocket服务器: ");
  Serial.print(websocket_server);
  Serial.print(":");
  Serial.println(websocket_port);
  
  // 设置WebSocket事件处理
  webSocket.begin(websocket_server, websocket_port, websocket_path);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);  // 5秒重连间隔
}

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
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
      Serial.println("可用命令: start, stop, status");
      isCapturing = false;  // 连接后默认不采集
      break;
      
    case WStype_TEXT:
      {
        String command = String((char*)payload);
        command.trim();
        command.toLowerCase();
        
        Serial.print("收到命令: ");
        Serial.println(command);
        
        if (command == "start") {
          if (!isCapturing) {
            isCapturing = true;
            Serial.println(">>> 开始采集和上传摄像头数据");
            // 发送确认消息
            webSocket.sendTXT("ACK: 开始采集");
          } else {
            Serial.println(">>> 已经在采集中");
            webSocket.sendTXT("ACK: 已在采集中");
          }
        }
        else if (command == "stop") {
          if (isCapturing) {
            isCapturing = false;
            Serial.println(">>> 停止采集和上传");
            // 发送确认消息
            webSocket.sendTXT("ACK: 停止采集");
          } else {
            Serial.println(">>> 当前未在采集");
            webSocket.sendTXT("ACK: 未在采集");
          }
        }
        else if (command == "status") {
          String status = isCapturing ? "采集中" : "已停止";
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

void updateLED() {
  unsigned long currentTime = millis();
  
  switch(currentState) {
    case STATE_WIFI_CONNECTING:
      // 闪烁（500ms间隔）
      if (currentTime - lastLedUpdate >= 500) {
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
        lastLedUpdate = currentTime;
      }
      break;
      
    case STATE_WEBSOCKET_CONNECTING:
      // 闪烁（500ms间隔）
      if (currentTime - lastLedUpdate >= 500) {
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
        lastLedUpdate = currentTime;
      }
      break;
      
    case STATE_CONNECTED:
      if (isCapturing) {
        // 采集中：常亮
        digitalWrite(LED_PIN, LOW);  // LED亮
      } else {
        // 未采集：每3秒亮300ms
        unsigned long cycleTime = (currentTime - lastLedUpdate) % 3000;
        if (cycleTime < 300) {
          digitalWrite(LED_PIN, LOW);  // LED亮
        } else {
          digitalWrite(LED_PIN, HIGH); // LED灭
        }
        // 更新lastLedUpdate以保持周期
        if (currentTime - lastLedUpdate >= 3000) {
          lastLedUpdate = currentTime;
        }
      }
      break;
      
    case STATE_ERROR:
      {
        // 每6秒亮300ms
        unsigned long errorCycleTime = (currentTime - lastErrorCycle) % 6000;
        if (errorCycleTime < 300) {
          digitalWrite(LED_PIN, LOW);  // LED亮
        } else {
          digitalWrite(LED_PIN, HIGH); // LED灭
        }
        // 更新lastErrorCycle以保持周期
        if (currentTime - lastErrorCycle >= 6000) {
          lastErrorCycle = currentTime;
        }
      }
      break;
  }
}

void checkConnections() {
  // 检查WiFi连接
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi连接丢失，尝试重连...");
    currentState = STATE_WIFI_CONNECTING;
    connectWiFi();
    connectWebSocket();
    return;
  }
  
  // 检查WebSocket连接
  if (currentState != STATE_CONNECTED && currentState != STATE_WEBSOCKET_CONNECTING) {
    if (currentState == STATE_ERROR) {
      Serial.println("WebSocket连接失败，尝试重连...");
      connectWebSocket();
    }
  }
}

void sendCameraFrame() {
  if (currentState == STATE_CONNECTED && webSocket.isConnected() && isCapturing) {
    // 捕获摄像头帧
    camera_fb_t * fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("摄像头捕获失败");
      return;
    }
    
    // 通过WebSocket发送JPEG二进制数据
    if (webSocket.sendBIN(fb->buf, fb->len)) {
      // 发送成功（可选：打印帧大小）
      // Serial.printf("发送帧: %u 字节\n", fb->len);
    } else {
      Serial.println("WebSocket发送失败");
    }
    
    // 释放帧缓冲区
    esp_camera_fb_return(fb);
  }
}

void loop() {
  // 更新LED状态
  updateLED();
  
  // 处理WebSocket事件
  webSocket.loop();
  
  // 检查连接状态
  checkConnections();
  
  // 如果连接成功且正在采集，持续发送摄像头帧
  if (currentState == STATE_CONNECTED && webSocket.isConnected() && isCapturing) {
    sendCameraFrame();
    // 不添加延迟，尽可能快地发送帧
  }
  
  delay(10);  // 短暂延迟，避免CPU占用过高
}
