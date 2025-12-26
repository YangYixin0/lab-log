# Lab Log 试用版 App - 部署指南

## 1. 配置 API Key

在部署前，必须在配置文件中设置有效的阿里云 API Key：

编辑文件：`app/src/main/assets/config.properties`

```properties
dashscope_api_key=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

## 2. 调整使用限制（可选）

如需修改免费使用次数，编辑同一文件：

```properties
max_api_calls=10  # 修改为所需次数
```

## 3. 构建 APK

### 使用 Android Studio

1. 打开 Android Studio
2. 选择 "File" → "Open"
3. 选择 `android-app-trial` 目录
4. 等待 Gradle 同步完成
5. 选择 "Build" → "Build Bundle(s) / APK(s)" → "Build APK(s)"
6. APK 位于：`app/build/outputs/apk/debug/app-debug.apk`

### 使用命令行

```bash
cd android-app-trial
./gradlew assembleDebug
```

生成的 APK：`app/build/outputs/apk/debug/app-debug.apk`

## 4. 签名 APK（可选，用于发布）

### 生成签名密钥

```bash
keytool -genkey -v -keystore lab-log-trial.keystore \
  -alias lab-log-trial \
  -keyalg RSA -keysize 2048 -validity 10000
```

### 签名 APK

```bash
jarsigner -verbose -sigalg SHA1withRSA -digestalg SHA1 \
  -keystore lab-log-trial.keystore \
  app/build/outputs/apk/debug/app-debug.apk lab-log-trial
```

### 或在 `app/build.gradle.kts` 中配置签名

```kotlin
android {
    signingConfigs {
        create("release") {
            storeFile = file("../lab-log-trial.keystore")
            storePassword = "your-password"
            keyAlias = "lab-log-trial"
            keyPassword = "your-password"
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true  // 启用代码混淆
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
}
```

然后构建 Release 版本：

```bash
./gradlew assembleRelease
```

## 5. 分发 APK

### 方法 1：直接分发

将 APK 文件上传到：
- 文件分享服务（如百度网盘、OneDrive）
- 自己的服务器
- GitHub Releases

用户需要：
1. 下载 APK
2. 在设置中允许"未知来源"安装
3. 安装 APK

### 方法 2：通过应用商店

- **Google Play**：需要开发者账号（$25 一次性费用）
- **华为应用市场**：免费，但需审核
- **小米应用商店**：免费，但需审核
- **其他国内应用商店**：各有不同要求

## 6. 使用说明文档

创建一个简单的用户指南（Markdown 或 PDF）：

```markdown
# Lab Log 试用版使用说明

## 安装

1. 下载 `lab-log-trial.apk`
2. 在手机设置中允许安装未知来源应用
3. 点击 APK 文件安装

## 使用

### 录制视频
1. 打开应用，授予相机权限
2. 点击"开始录制"
3. 录制最长 60 秒
4. 点击"停止录制"

### 理解视频
1. 录制完成后自动跳转到详情页
2. 应用会自动调用 AI 分析视频
3. 查看事件表和人物外貌表

### 查看历史
1. 点击底部"历史"按钮
2. 查看所有录制记录
3. 点击记录查看详情

## 限制

- 免费使用 10 次
- 每次最长录制 60 秒
- 需要网络连接

## 技术支持

如有问题，请联系：[your-email@example.com]
```

## 7. 注意事项

### 安全性

⚠️ **重要**：当前版本的 API Key 是明文存储在配置文件中的，容易被提取。建议：

1. **短期方案**：
   - 使用临时 API Key
   - 设置 API Key 的使用配额和有效期
   - 监控 API 使用情况

2. **长期方案**（需要额外开发）：
   - 实现 API Gateway 中间层
   - 使用设备指纹绑定
   - 添加代码混淆（ProGuard/R8）
   - 实现请求签名机制

### 使用次数重置

用户的使用次数存储在 SharedPreferences 中，可以通过以下方式重置：

1. **用户端**：清除应用数据
2. **开发端**：提供重置功能（需要密码保护）

### 性能优化

- 视频文件较大时，上传可能耗时较长
- 建议提示用户在 WiFi 环境下使用
- 可以考虑添加断点续传功能

## 8. 监控和反馈

### API 使用监控

在阿里云控制台监控：
- API 调用次数
- 失败率
- 响应时间

### 用户反馈收集

建议添加：
- 应用内反馈功能
- 崩溃日志收集（如使用 Firebase Crashlytics）
- 用户行为分析（如使用 Firebase Analytics）

## 9. 更新和维护

### 版本更新

修改 `app/build.gradle.kts` 中的版本号：

```kotlin
defaultConfig {
    versionCode = 2  // 递增
    versionName = "1.1"
}
```

### 发布新版本

1. 修改代码
2. 更新版本号
3. 构建新的 APK
4. 分发给用户

### 通知用户更新

可以考虑：
- 在应用启动时检查版本
- 显示更新通知
- 提供下载链接

## 10. 常见问题解决

### 问题：应用崩溃

**解决方案**：
1. 查看 logcat 日志
2. 检查权限是否授予
3. 检查设备兼容性

### 问题：理解失败

**解决方案**：
1. 检查网络连接
2. 检查 API Key 是否有效
3. 检查 API 配额是否用尽

### 问题：视频播放失败

**解决方案**：
1. 检查设备是否支持 H.265
2. 降级到 H.264（修改配置）
3. 使用其他播放器

## 联系方式

如有技术问题，请联系：
- Email: [your-email@example.com]
- GitHub: [your-github-repo]


