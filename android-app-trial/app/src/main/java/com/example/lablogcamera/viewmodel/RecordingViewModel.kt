package com.example.lablogcamera.viewmodel

import android.annotation.SuppressLint
import android.app.Application
import android.graphics.Rect
import android.hardware.camera2.CameraCharacteristics
import android.util.Log
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.lablogcamera.storage.StorageManager
import com.example.lablogcamera.utils.ConfigManager
import com.example.lablogcamera.utils.OcrBFontRenderer
import com.example.lablogcamera.utils.VideoEncoder
import com.example.lablogcamera.utils.applyResolutionLimit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.Executors

private const val TAG = "RecordingViewModel"

/**
 * 录制状态
 */
enum class RecordingState {
    IDLE,          // 未录制
    RECORDING,     // 录制中
    COMPLETED      // 录制完成
}

/**
 * 录制界面 ViewModel
 */
class RecordingViewModel(application: Application) : AndroidViewModel(application) {
    private val storageManager = StorageManager(application)
    private val analysisExecutor = Executors.newSingleThreadExecutor()
    
    // 录制状态
    private val _recordingState = MutableStateFlow(RecordingState.IDLE)
    val recordingState: StateFlow<RecordingState> = _recordingState.asStateFlow()
    
    // 录制时长（秒）
    private val _recordingDuration = MutableStateFlow(0)
    val recordingDuration: StateFlow<Int> = _recordingDuration.asStateFlow()
    
    // 当前帧率
    private val _currentFps = MutableStateFlow(0f)
    val currentFps: StateFlow<Float> = _currentFps.asStateFlow()
    
    // 提示词
    private val _prompt = MutableStateFlow(com.example.lablogcamera.service.VideoUnderstandingService.DEFAULT_PROMPT)
    val prompt: StateFlow<String> = _prompt.asStateFlow()
    
    // 错误消息
    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()
    
    // 录制完成后的视频 ID
    private val _completedVideoId = MutableStateFlow<String?>(null)
    val completedVideoId: StateFlow<String?> = _completedVideoId.asStateFlow()
    
    // ImageAnalysis
    val imageAnalysis = mutableStateOf<ImageAnalysis?>(null)
    
    // ImageAnalysis 实际分辨率（用于动态调整预览宽高比）
    private val _analysisResolution = MutableStateFlow<Pair<Int, Int>?>(null)
    val analysisResolution: StateFlow<Pair<Int, Int>?> = _analysisResolution.asStateFlow()
    
    // 设备物理方向（0=竖放, 90=右横, 180=倒置, 270=左横）
    private val _devicePhysicalRotation = MutableStateFlow(0)
    
    /**
     * 更新设备物理方向（从 UI 的 OrientationEventListener 调用）
     */
    fun updateDevicePhysicalRotation(rotation: Int) {
        _devicePhysicalRotation.value = rotation
    }
    
    /**
     * 根据设备物理旋转计算后端需要的 rotation 值
     * 后置摄像头：rotationForBackend = (physicalRotation + 90) % 360
     */
    private fun calculateRotationForBackend(physicalRotation: Int): Int {
        return (physicalRotation + 90) % 360
    }
    
    // 视频编码器
    private var videoEncoder: VideoEncoder? = null
    
    // 录制开始时间
    private var recordingStartTime: Long = 0
    
    // 帧率计算
    private var frameCount = 0
    private var lastFpsUpdateTime = 0L
    
    // 分辨率
    private var encoderWidth = 0
    private var encoderHeight = 0
    
    init {
        // 初始化配置
        ConfigManager.initialize(application)
        
        // 初始化 OCR-B 字体
        OcrBFontRenderer.initialize(application)
        
        // 预加载字符（后台线程）
        viewModelScope.launch(Dispatchers.IO) {
            OcrBFontRenderer.preloadAllCharacters(20, 30)
        }
    }
    
    /**
     * 创建 ImageAnalysis（在 startRecording 时创建并设置 analyzer）
     */
    fun createImageAnalysis(): ImageAnalysis {
        val resolutionLimit = ConfigManager.videoResolutionLimit
        
        val analysis = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
            .build()
        
        // 不在这里设置 analyzer，在 startRecording 时设置
        imageAnalysis.value = analysis
        return analysis
    }
    
    /**
     * 处理帧
     */
    @SuppressLint("UnsafeOptInUsageError")
    private fun processFrame(image: ImageProxy, resolutionLimit: Int) {
        // 应用分辨率上限
        val imageWidth = image.width
        val imageHeight = image.height
        val (targetWidth, targetHeight) = applyResolutionLimit(imageWidth, imageHeight, resolutionLimit)
        
        // 更新实际分辨率（如果与预期不同）
        val currentResolution = _analysisResolution.value
        if (currentResolution == null || currentResolution.first != targetWidth || currentResolution.second != targetHeight) {
            _analysisResolution.value = Pair(targetWidth, targetHeight)
            Log.d(TAG, "ImageAnalysis actual resolution updated: ${targetWidth}x${targetHeight}")
        }
        
        // 计算裁剪区域
        val cropRect = if (targetWidth != imageWidth || targetHeight != imageHeight) {
            // 需要裁剪，居中裁剪
            val left = (imageWidth - targetWidth) / 2
            val top = (imageHeight - targetHeight) / 2
            Rect(left, top, left + targetWidth, top + targetHeight)
        } else {
            // 不需要裁剪
            Rect(0, 0, imageWidth, imageHeight)
        }
        
        // 只在录制时处理帧
        if (_recordingState.value == RecordingState.RECORDING) {
            // 第一帧：初始化编码器
            if (videoEncoder == null) {
                val bitrate = (ConfigManager.videoBitrateMbps * 1_000_000).toInt()
                val fps = ConfigManager.videoFps
                
                videoEncoder = VideoEncoder(
                    preferH265 = ConfigManager.preferH265,
                    onVideoComplete = { _, _ -> }
                )
                
                encoderWidth = targetWidth
                encoderHeight = targetHeight
                
                videoEncoder?.start(encoderWidth, encoderHeight, bitrate, fps)
                
                Log.d(TAG, "Encoder initialized: ImageAnalysis actual=${imageWidth}x${imageHeight}, encoder=${encoderWidth}x${encoderHeight}, bitrate=${bitrate}bps, fps=${fps}fps")
            }
            
            val encoder = videoEncoder
            if (encoder != null) {
                // 计算当前时间戳
                val currentTime = System.currentTimeMillis()
                val elapsedSeconds = ((currentTime - recordingStartTime) / 1000).toInt()
                
                // 更新录制时长
                _recordingDuration.value = elapsedSeconds
                
                // 检查是否达到最大时长
                if (elapsedSeconds >= ConfigManager.videoMaxDurationSeconds) {
                    viewModelScope.launch {
                        stopRecording()
                    }
                    return
                }
                
                // 生成时间戳字符串
                val sdf = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
                val timestampStr = "Time: ${sdf.format(Date(currentTime))}"
                
                // 根据设备物理方向动态计算旋转角度
                val physicalRotation = _devicePhysicalRotation.value
                val rotationForEncoding = calculateRotationForBackend(physicalRotation)
                
                // 编码帧（根据手机姿态动态旋转）
                encoder.encode(
                    image = image,
                    cropRect = cropRect,
                    rotationDegrees = rotationForEncoding,
                    timestamp = timestampStr,
                    charWidth = 20,
                    charHeight = 30
                )
                
                // 更新帧率
                frameCount++
                if (currentTime - lastFpsUpdateTime >= 1000) {
                    _currentFps.value = frameCount.toFloat()
                    frameCount = 0
                    lastFpsUpdateTime = currentTime
                }
            }
        }
    }
    
    /**
     * 开始录制
     */
    fun startRecording() {
        if (_recordingState.value != RecordingState.IDLE) {
            Log.w(TAG, "Cannot start recording: state=${_recordingState.value}")
            return
        }
        
        viewModelScope.launch(Dispatchers.IO) {
            try {
                // 清理旧的编码器（确保每次录制都是全新的）
                videoEncoder?.stop()
                videoEncoder = null
                
                // 使用配置的分辨率上限
                val resolutionLimit = ConfigManager.videoResolutionLimit
                
                // 创建高分辨率的 ImageAnalysis（请求最大可能的分辨率）
                // 参考原始 MainActivity.kt，使用 setTargetResolution 明确请求高分辨率
                val targetResolution = android.util.Size(resolutionLimit, resolutionLimit)
                
                Log.d(TAG, "Requesting ImageAnalysis resolution: ${targetResolution.width}x${targetResolution.height}")
                
                val analysisBuilder = ImageAnalysis.Builder()
                    .setTargetResolution(targetResolution)  // 请求 1920×1920
                    .setTargetRotation(android.view.Surface.ROTATION_0)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                
                val analysis = analysisBuilder.build()
                
                // 预先设置预期的分辨率（以便 UI 能立即绑定相机）
                // 实际分辨率会在第一帧到达后更新
                withContext(Dispatchers.Main) {
                    _analysisResolution.value = Pair(resolutionLimit, resolutionLimit)
                }
                
                // 设置 Analyzer（在第一帧时获取实际分辨率并启动编码器）
                analysis.setAnalyzer(Executors.newSingleThreadExecutor()) { imageProxy ->
                    try {
                        processFrame(imageProxy, resolutionLimit)
                    } catch (e: Exception) {
                        Log.e(TAG, "Error processing frame", e)
                    } finally {
                        imageProxy.close()
                    }
                }
                
                // 更新 ImageAnalysis（这会触发 CameraPreview 重新绑定相机）
                withContext(Dispatchers.Main) {
                    imageAnalysis.value = analysis
                }
                
                // 等待相机绑定和第一帧到达
                delay(100)
                
                // 更新状态为录制中
                recordingStartTime = System.currentTimeMillis()
                lastFpsUpdateTime = recordingStartTime
                frameCount = 0
                _recordingDuration.value = 0
                _recordingState.value = RecordingState.RECORDING
                
                Log.d(TAG, "Recording state changed to RECORDING")
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start recording", e)
                _errorMessage.value = "录制失败: ${e.message}"
                _recordingState.value = RecordingState.IDLE
            }
        }
    }
    
    /**
     * 停止录制
     */
    fun stopRecording() {
        if (_recordingState.value != RecordingState.RECORDING) {
            Log.w(TAG, "Cannot stop recording: state=${_recordingState.value}")
            return
        }
        
        viewModelScope.launch(Dispatchers.IO) {
            try {
                // 停止编码器并获取视频数据
                val result = videoEncoder?.stop()
                videoEncoder = null
                
                if (result != null) {
                    val (mp4Data, metadata) = result
                    
                    // 保存视频文件
                    val videoId = storageManager.generateId()
                    val videoPath = storageManager.saveVideo(videoId, mp4Data)
                    
                    // 生成缩略图
                    storageManager.generateThumbnail(videoPath, videoId)
                    
                    Log.d(TAG, "Recording saved: $videoId, size=${mp4Data.size}, frames=${metadata.frameCount}")
                    
                    // 更新状态
                    _completedVideoId.value = videoId
                    _recordingState.value = RecordingState.COMPLETED
                } else {
                    _errorMessage.value = "保存视频失败"
                    _recordingState.value = RecordingState.IDLE
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to stop recording", e)
                _errorMessage.value = "停止录制失败: ${e.message}"
                _recordingState.value = RecordingState.IDLE
            }
        }
    }
    
    /**
     * 重新录制
     */
    fun resetRecording() {
        viewModelScope.launch {
            // 清理旧的编码器
            videoEncoder?.stop()
            videoEncoder = null
            
            // 删除之前的录制
            _completedVideoId.value?.let { videoId ->
                storageManager.deleteRecording(videoId)
            }
            
            _completedVideoId.value = null
            _recordingState.value = RecordingState.IDLE
            _recordingDuration.value = 0
            _currentFps.value = 0f
            _errorMessage.value = null
        }
    }
    
    /**
     * 更新提示词
     */
    fun updatePrompt(newPrompt: String) {
        _prompt.value = newPrompt
    }
    
    /**
     * 重置提示词
     */
    fun resetPrompt() {
        _prompt.value = com.example.lablogcamera.service.VideoUnderstandingService.DEFAULT_PROMPT
    }
    
    /**
     * 清除错误消息
     */
    fun clearError() {
        _errorMessage.value = null
    }
    
    /**
     * 清除已完成的视频ID（避免重复导航）
     */
    fun clearCompletedVideo() {
        _completedVideoId.value = null
    }
    
    override fun onCleared() {
        super.onCleared()
        analysisExecutor.shutdown()
        videoEncoder?.stop()
    }
}

