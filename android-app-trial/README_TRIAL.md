# Lab Log 试用版 App

这是 Lab Log 的试用版 Android 应用，无需后端，直接调用阿里云大模型进行视频理解。

## 功能特性

- ✅ **视频录制**：最长 60 秒，支持 H.265/H.264 编码
- ✅ **动态旋转**：根据手机物理姿态自动旋转视频方向
- ✅ **时间戳水印**：使用 OCRB 字体在视频上叠加时间戳
- ✅ **视频理解**：调用阿里云 Qwen3-VL 或 OpenRouter Gemini 大模型分析视频
  - 支持 `qwen3-vl-flash`、`qwen3-vl-plus` 以及 `Gemini-2.5-Flash` (OpenRouter) 模型选择
  - 可自定义提示词，支持重置为默认值
  - 支持配置视频理解参数（FPS、thinking、temperature 等）
- ✅ **流式输出**：实时显示理解进度
- ✅ **事件表和人物外貌表**：结构化显示理解结果
- ✅ **JSON 查看**：支持在表格视图和原始 JSON 之间切换
- ✅ **历史记录**：保存所有录制和理解结果，支持删除
- ✅ **CSV 导出**：一键复制事件表和外貌表到剪贴板
- ✅ **使用次数限制**：默认 10 次免费使用，显示"已理解 n/m 次"
- ✅ **视频信息折叠**：详情页视频信息可展开/折叠
- ✅ **快速重新录制**：停止录制后直接显示"开始录制"，一键重新开始

## 配置

在 `app/src/main/assets/config.properties` 中配置：

```properties
# API 配置
dashscope_api_key=your_api_key_here
openrouter_api_key=your_openrouter_key_here
qwen_model=qwen3-vl-flash

# 视频参数
video_resolution_limit=1920
video_bitrate_mbps=1.0
video_fps=4
video_max_duration_seconds=60

# 编码格式（优先H.264）
video_codec_priority=h264,h265

# 使用次数限制
max_api_calls=10

# 超时设置（毫秒）
api_timeout_ms=120000

# 视频理解参数
video_fps=2.0
enable_thinking=true
thinking_budget=8192
vl_high_resolution_images=true
vl_temperature=0.1
vl_top_p=0.7
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

- [ ] **视频理解参数对话框**：点击"开始理解"/"重新理解"按钮打开对话框
- [ ] **模型选择**：在 qwen3-vl-flash、qwen3-vl-plus 和 Gemini-2.5-Flash 之间切换
- [ ] **提示词编辑**：修改提示词内容
- [ ] **提示词重置**：点击"重置"按钮恢复默认提示词
- [ ] **发起理解**：点击"开始理解"按钮
- [ ] **多次理解**：同一视频可以理解多次
- [ ] **结果展示**：每次理解结果独立显示
- [ ] **JSON 查看**：在表格视图和 JSON 视图之间切换

### 5. 边界情况测试

- [ ] **60秒自动停止**：录制 60 秒后自动停止
- [ ] **快速重新录制**：停止录制后直接点击"开始录制"按钮
- [ ] **非 JSON 响应**：API 返回非 JSON 格式时显示错误而不是崩溃
- [ ] **网络错误**：无网络时显示错误提示
- [ ] **API 超时**：等待 2 分钟后允许重试
- [ ] **使用次数限制**：达到 10 次后禁用理解功能，显示"使用次数已达上限"
- [ ] **存储空间不足**：提示用户清理空间
- [ ] **视频文件损坏**：显示错误提示
- [ ] **Android 8.1 兼容性**：在 Android 8.1 设备上正常录制和播放

### 6. UI/UX 测试

- [ ] **导航栏**：录制/历史切换正常
- [ ] **标题栏**：显示"Lab Log 试用版"和使用次数（格式：已理解 n/m 次）
- [ ] **视频信息折叠**：详情页视频信息可展开/折叠
- [ ] **视频理解参数对话框**：对话框宽度和高度合适，内容可滚动
- [ ] **提示词区域**：可编辑、重置、复制，字体大小合适
- [ ] **错误提示**：错误消息清晰易懂，非 JSON 响应时显示友好提示
- [ ] **加载指示**：显示加载状态
- [ ] **相机预览**：预览容器宽高比动态适配，不撑大容器

## 已知限制

1. **使用次数限制**：默认 10 次，计数存储在 SharedPreferences 中
2. **API Key 保护**：配置文件中明文存储，容易被提取（待后续优化）
3. **H.265 兼容性**：部分设备不支持 H.265，会自动回退到 H.264
4. **分辨率上限**：默认 1920，超过会裁剪为正方形
5. **视频时长**：最长 60 秒，无法分段
6. **预览与录制 FOV 不一致**：部分设备（如 Android 8.1 OPPO）上预览视野与录制结果视野可能不完全一致（已知问题，暂未解决）

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

### 架构更新

#### 相机预览与录制同步

- **ViewPort + UseCaseGroup**：使用 `ViewPort` 和 `UseCaseGroup` 确保 `Preview` 和 `ImageAnalysis` 共享相同的视野（FOV），避免预览和录制内容不一致
- **显示旋转处理**：预览容器的宽高比基于 `display.rotation`（屏幕显示方向）而非设备物理方向，确保预览正确显示
- **动态宽高比适配**：预览容器根据 `ImageAnalysis` 实际分辨率和显示旋转动态计算宽高比，避免容器被撑大

#### 视频编码改进

- **动态旋转支持**：根据设备物理姿态（`OrientationEventListener`）动态计算编码旋转角度，确保录制的视频方向正确
- **编码尺寸匹配**：编码器尺寸根据旋转角度调整（90/270 度时交换宽高），避免画面出现虚影
- **MediaMuxer 启动时机**：等待 `MediaCodec.INFO_OUTPUT_FORMAT_CHANGED` 事件，确保获取到 SPS/PPS（csd-0/csd-1）后再启动 muxer，解决 Android 8.1 上的"无法播放此视频"问题

#### Android 8.1 兼容性

- **YUV 数据完整性检查**：对 `ImageProxy` 提供的 YUV 数据进行大小验证，数据不完整时智能填充（Y 平面填充黑色，UV 平面填充中性色）
- **避免过度对齐**：移除 32 字节对齐限制，只确保宽高为偶数，避免数据截断
- **Muxer 启动兜底逻辑**：如果 `INFO_OUTPUT_FORMAT_CHANGED` 未触发，从首个关键帧或 CODEC_CONFIG 缓冲区提取 SPS/PPS，确保 muxer 能够启动

### 依赖项

- CameraX 1.4.0
- Compose BOM
- OkHttp 4.12.0
- Gson 2.10.1
- Navigation Compose 2.7.6
- Accompanist Permissions 0.34.0

## 调试经验

### Android 8.1 兼容性问题

#### 问题 1：YUV 数据不完整
**现象**：录制后视频文件为 0 字节，日志显示 "YUV data size mismatch"

**原因**：Android 8.1 上 `ImageProxy` 提供的 YUV buffer 可能不完整，实际数据大小小于预期

**解决方案**：
- 添加数据大小验证，如果数据不完整（<50% 预期大小）则跳过该帧
- 如果数据部分完整（50%-100%），智能填充缺失部分：
  - Y 平面（亮度）填充为 16（黑色）
  - UV 平面（色度）填充为 128（中性灰色）

#### 问题 2：MediaMuxer 未启动
**现象**：录制后视频文件为 0 字节，日志显示 "Skipping frame: isStarted=false, videoTrackIndex=-1"

**原因**：部分设备（特别是 Android 8.1）的 H.264 编码器不会立即触发 `INFO_OUTPUT_FORMAT_CHANGED`，导致无法获取 SPS/PPS（csd-0/csd-1），muxer 无法启动

**解决方案**：
1. 移除在 `start()` 阶段主动启动 muxer 的逻辑
2. 在编码循环中等待 `INFO_OUTPUT_FORMAT_CHANGED` 事件
3. 如果仍未获取到 csd-0，从首个关键帧或 `BUFFER_FLAG_CODEC_CONFIG` 缓冲区提取 SPS/PPS
4. 添加兜底逻辑：如果到首个关键帧仍未启动，强制使用当前 `outputFormat` 启动 muxer（即使没有 csd）

#### 问题 3：视频画面虚影
**现象**：录制的视频在水平方向出现四个虚影

**原因**：编码器尺寸与旋转后的视频尺寸不匹配。当设备旋转 90/270 度时，需要交换编码器的宽高，但代码中未正确处理

**解决方案**：在初始化编码器时，根据 `calculateRotationForBackend()` 的结果，如果旋转角度为 90/270 度，则交换 `encoderWidth` 和 `encoderHeight`

### 预览与录制 FOV 同步

#### 问题：预览视野与录制结果不一致
**现象**：预览显示的内容与录制结果视野范围不同（如预览是 720×540，录制是 960×720）

**原因**：
1. `Preview` 和 `ImageAnalysis` 使用了不同的旋转设置
2. `ViewPort` 的宽高比计算不正确
3. 预览容器的宽高比基于设备物理方向而非显示方向

**解决方案**：
1. 使用 `ViewPort` + `UseCaseGroup` 统一 `Preview` 和 `ImageAnalysis` 的 FOV
2. `ViewPort` 的宽高比基于 `ImageAnalysis` 实际分辨率和显示旋转计算
3. 预览容器的宽高比也基于显示旋转（`display.rotation`）而非设备物理方向
4. 确保 `Preview`、`ImageAnalysis` 和 `ViewPort` 使用相同的 `targetRotation`

**注意**：部分设备（如 Android 8.1 OPPO）上仍可能存在轻微的 FOV 不一致，这是设备特定的问题，暂未完全解决

### 其他调试经验

1. **显示旋转 vs 设备物理旋转**：
   - `display.rotation`：屏幕显示方向（0/90/180/270），用于预览
   - `OrientationEventListener`：设备物理方向，用于视频编码旋转
   - 两者可能不同（如屏幕锁定方向时）

2. **MediaExtractor vs MediaMetadataRetriever**：
   - `MediaMetadataRetriever.METADATA_KEY_CAPTURE_FRAMERATE` 在部分设备上不可靠，总是返回 0.0
   - 使用 `MediaExtractor` 从视频轨道的 `MediaFormat.KEY_FRAME_RATE` 获取帧率更可靠

3. **ImageProxy 资源管理**：
   - 确保每个 `ImageProxy` 只关闭一次，避免在 `finally` 块和外部都关闭导致 "maxImages has already been acquired" 错误

4. **JSON 解析错误处理**：
   - API 可能返回非 JSON 格式（如 HTML 错误页面）
   - 在 `VideoUnderstandingService.parseResult()` 中捕获 JSON 解析异常，设置 `parseError` 字段
   - UI 层检查 `parseError` 并显示友好提示，而不是崩溃

## 故障排除

### 1. 相机预览黑屏

- 检查相机权限是否授予
- 检查设备是否支持后置摄像头

### 2. 录制失败

- 检查存储空间是否充足
- 检查日志中的编码器错误
- **Android 8.1 设备**：检查日志中是否有 "YUV data size mismatch" 或 "Skipping frame: isStarted=false"
  - 如果出现 YUV 数据不完整，这是设备兼容性问题，已通过智能填充处理
  - 如果 muxer 未启动，检查是否收到 `INFO_OUTPUT_FORMAT_CHANGED` 事件

### 3. 理解失败

- 检查网络连接
- 检查 API Key 是否正确配置
- 检查是否达到使用次数限制
- 查看日志中的 API 响应

### 4. 视频播放失败

- 检查视频文件是否存在
- 检查设备是否支持 H.265 解码
- 检查视频文件大小是否为 0 字节（可能是 muxer 未启动）

### 5. 预览与录制不一致

- 检查设备 Android 版本（Android 8.1 可能存在已知问题）
- 检查日志中 ViewPort 的宽高比是否正确
- 检查 `Preview` 和 `ImageAnalysis` 是否使用相同的 `targetRotation`

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
6. **FOV 同步优化**：进一步优化预览与录制的视野同步，特别是 Android 8.1 设备
7. **编码器优化**：改进 YUV 数据处理，减少数据填充的情况
8. **错误恢复**：改进 muxer 启动失败时的错误恢复机制


