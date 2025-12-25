# Lab Log 试用版 App

这是 Lab Log 的试用版 Android 应用，无需后端，直接调用阿里云大模型进行视频理解。

## 功能特性

- ✅ **视频录制**：最长 60 秒，支持 H.265/H.264 编码
- ✅ **时间戳水印**：使用 OCRB 字体在视频上叠加时间戳
- ✅ **视频理解**：调用阿里云 Qwen3-VL 大模型分析视频
- ✅ **流式输出**：实时显示理解进度
- ✅ **事件表和人物外貌表**：结构化显示理解结果
- ✅ **历史记录**：保存所有录制和理解结果
- ✅ **CSV 导出**：一键复制事件表和外貌表到剪贴板
- ✅ **使用次数限制**：默认 10 次免费使用

## 配置

在 `app/src/main/assets/config.properties` 中配置：

```properties
# API 配置
dashscope_api_key=your_api_key_here
qwen_model=qwen3-vl-flash

# 视频参数
video_resolution_limit=1920
video_bitrate_mbps=2.0
video_fps=4
video_max_duration_seconds=60

# 编码格式（优先H.265，不支持回退H.264）
video_codec_priority=h265,h264

# 使用次数限制
max_api_calls=10

# 超时设置（毫秒）
api_timeout_ms=120000
```

## 构建

```bash
cd /root/lab-log/android-app-trial
./gradlew assembleDebug
```

生成的 APK 位于：`app/build/outputs/apk/debug/app-debug.apk`

## 测试清单

### 1. 基础功能测试

- [ ] **启动应用**：检查权限请求
- [ ] **相机预览**：预览正常显示
- [ ] **开始录制**：点击"开始录制"按钮
- [ ] **录制过程**：显示帧率、红点指示、时长
- [ ] **停止录制**：点击"停止录制"按钮
- [ ] **自动跳转**：录制完成后自动跳转到详情页

### 2. 视频理解测试

- [ ] **视频播放**：详情页播放器正常工作
- [ ] **视频信息**：显示分辨率、帧率、码率、编码格式
- [ ] **流式输出**：理解过程中实时显示文本
- [ ] **事件解析**：正确解析事件表
- [ ] **外貌解析**：正确解析人物外貌表
- [ ] **提示词显示**：显示所用提示词
- [ ] **CSV 复制**：复制事件表和外貌表到剪贴板

### 3. 历史记录测试

- [ ] **列表显示**：显示所有录制记录
- [ ] **缩略图**：显示视频缩略图
- [ ] **时间戳**：显示正确的时间戳
- [ ] **点击进入**：点击记录进入详情页
- [ ] **刷新**：点击刷新按钮

### 4. 重新理解测试

- [ ] **编辑提示词**：在详情页修改提示词
- [ ] **发起理解**：点击"重新理解"按钮
- [ ] **多次理解**：同一视频可以理解多次
- [ ] **结果展示**：每次理解结果独立显示

### 5. 边界情况测试

- [ ] **60秒自动停止**：录制 60 秒后自动停止
- [ ] **重新录制**：点击"重新录制"按钮
- [ ] **网络错误**：无网络时显示错误提示
- [ ] **API 超时**：等待 2 分钟后允许重试
- [ ] **使用次数限制**：达到 10 次后禁用理解功能
- [ ] **存储空间不足**：提示用户清理空间
- [ ] **视频文件损坏**：显示错误提示

### 6. UI/UX 测试

- [ ] **导航栏**：录制/历史切换正常
- [ ] **标题栏**：显示"Lab Log 试用版"和使用次数
- [ ] **提示词区域**：可编辑、重置、复制
- [ ] **错误提示**：错误消息清晰易懂
- [ ] **加载指示**：显示加载状态

## 已知限制

1. **使用次数限制**：默认 10 次，计数存储在 SharedPreferences 中
2. **API Key 保护**：配置文件中明文存储，容易被提取（待后续优化）
3. **H.265 兼容性**：部分设备不支持 H.265，会自动回退到 H.264
4. **分辨率上限**：默认 1920，超过会裁剪为正方形
5. **视频时长**：最长 60 秒，无法分段

## 文件结构

```
android-app-trial/
├── app/
│   ├── src/main/
│   │   ├── assets/
│   │   │   ├── config.properties      # 配置文件
│   │   │   └── fonts/
│   │   │       └── OCRB_Regular.ttf   # OCR-B 字体
│   │   ├── java/com/example/lablogcamera/
│   │   │   ├── MainActivity.kt        # 主入口
│   │   │   ├── data/
│   │   │   │   └── Models.kt          # 数据模型
│   │   │   ├── service/
│   │   │   │   └── VideoUnderstandingService.kt
│   │   │   ├── storage/
│   │   │   │   └── StorageManager.kt
│   │   │   ├── ui/
│   │   │   │   ├── RecordingScreen.kt # 录制界面
│   │   │   │   ├── HistoryScreen.kt   # 历史记录
│   │   │   │   └── DetailScreen.kt    # 详情页
│   │   │   ├── utils/
│   │   │   │   ├── ConfigManager.kt
│   │   │   │   ├── UsageCounter.kt
│   │   │   │   ├── VideoEncoder.kt
│   │   │   │   └── OcrBFontRenderer.kt
│   │   │   └── viewmodel/
│   │   │       ├── RecordingViewModel.kt
│   │   │       ├── HistoryViewModel.kt
│   │   │       └── DetailViewModel.kt
```

## 开发说明

### 复用的代码

- `OcrBFontRenderer`：字体渲染器（来自 OriginalMainActivity.kt）
- `toNv12ByteArray`：YUV 转换和时间戳绘制
- `VideoEncoder`：基于 H264Encoder 改造，支持 H.265 和单段录制

### 新增功能

- `VideoUnderstandingService`：阿里云 API 调用和流式输出解析
- `StorageManager`：本地存储管理（视频、JSON、缩略图）
- `ConfigManager`：配置文件读取
- `UsageCounter`：使用次数计数

### 依赖项

- CameraX 1.4.0
- Compose BOM
- OkHttp 4.12.0
- Gson 2.10.1
- Navigation Compose 2.7.6
- Accompanist Permissions 0.34.0

## 故障排除

### 1. 相机预览黑屏

- 检查相机权限是否授予
- 检查设备是否支持后置摄像头

### 2. 录制失败

- 检查存储空间是否充足
- 检查日志中的编码器错误

### 3. 理解失败

- 检查网络连接
- 检查 API Key 是否正确配置
- 检查是否达到使用次数限制
- 查看日志中的 API 响应

### 4. 视频播放失败

- 检查视频文件是否存在
- 检查设备是否支持 H.265 解码

## 日志标签

- `ConfigManager`：配置加载
- `UsageCounter`：使用次数
- `VideoEncoder`：视频编码
- `OcrBFontRenderer`：字体渲染
- `VideoUnderstandingService`：API 调用
- `StorageManager`：存储管理
- `RecordingViewModel`：录制逻辑
- `DetailViewModel`：详情页逻辑
- `RecordingScreen`：录制界面
- `DetailScreen`：详情页

## 后续优化方向

1. **API Key 保护**：使用代码混淆、请求签名、设备指纹等
2. **设备指纹**：更可靠的使用次数限制
3. **离线支持**：保存失败的理解请求，网络恢复后重试
4. **性能优化**：减少内存占用，优化编码速度
5. **UI 优化**：更好的动画效果，更友好的交互

