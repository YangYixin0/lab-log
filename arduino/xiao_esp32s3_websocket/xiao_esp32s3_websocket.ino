/*
 * 功能描述：XIAO ESP32S3 Sense连接WPA2 Enterprise WiFi，通过WebSocket连接到服务器，
 *           每2秒发送0-100的随机整数。使用PIN21的LED显示连接状态。
 */
#include <WiFi.h>               // 用于基础的WiFi连接

#if __has_include("esp_eap_client.h")
#include "esp_eap_client.h"     // WPA2 Enterprise 认证
#else
#include "esp_wpa2.h"           // esp_eap_client.h的旧版本
#endif

#include "secrets.h"
const char *ssid = "eduroam";   // 网络SSID号

#include <WebSocketsClient.h>   // WebSocket客户端库

// WebSocket配置（从secrets.h读取）
const char *websocket_server = WEBSOCKET_SERVER;
const int websocket_port = WEBSOCKET_PORT;
const char *websocket_path = "/";

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

// 时间控制变量
unsigned long lastRandomSend = 0;
const unsigned long SEND_INTERVAL = 2000;  // 2秒发送一次

unsigned long lastLedUpdate = 0;
unsigned long lastErrorCycle = 0;
bool errorLedState = false;

void setup() {
  // 初始化串口
  Serial.begin(115200);
  delay(1000);
  
  // 初始化LED
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  
  Serial.println();
  Serial.println("=== XIAO ESP32S3 WebSocket Client ===");
  
  // 建立WiFi连接
  connectWiFi();
  
  // 建立WebSocket连接
  connectWebSocket();
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
      break;
      
    case WStype_TEXT:
      Serial.print("收到消息: ");
      Serial.println((char*)payload);
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
      // 快速闪烁（150ms间隔）
      if (currentTime - lastLedUpdate >= 150) {
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
        lastLedUpdate = currentTime;
      }
      break;
      
    case STATE_WEBSOCKET_CONNECTING:
      // 中速闪烁（500ms间隔）
      if (currentTime - lastLedUpdate >= 500) {
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
        lastLedUpdate = currentTime;
      }
      break;
      
    case STATE_CONNECTED:
      // 每2秒闪烁一次（与发送数据同步，发送时亮100ms）
      if (currentTime - lastRandomSend < 100) {
        // 发送数据时LED亮，XIAO ESP32S3 的 LED 亮起需要 LOW
        digitalWrite(LED_PIN, LOW);
      } else {
        digitalWrite(LED_PIN, HIGH);
      }
      break;
      
    case STATE_ERROR:
      // 常亮3秒后熄灭1秒，循环
      if (currentTime - lastErrorCycle >= (errorLedState ? 3000 : 1000)) {
        errorLedState = !errorLedState;
        digitalWrite(LED_PIN, errorLedState ? LOW : HIGH);
        lastErrorCycle = currentTime;
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

void sendRandomNumber() {
  if (currentState == STATE_CONNECTED && webSocket.isConnected()) {
    int randomNum = random(0, 101);  // 生成0-100的随机整数
    String message = String(randomNum);
    
    webSocket.sendTXT(message);
    Serial.print("发送随机数: ");
    Serial.println(randomNum);
    
    lastRandomSend = millis();
  }
}

void loop() {
  // 更新LED状态
  updateLED();
  
  // 处理WebSocket事件
  webSocket.loop();
  
  // 检查连接状态
  checkConnections();
  
  // 每2秒发送一次随机数
  if (currentState == STATE_CONNECTED && 
      millis() - lastRandomSend >= SEND_INTERVAL) {
    sendRandomNumber();
  }
  
  delay(10);  // 短暂延迟，避免CPU占用过高
}

