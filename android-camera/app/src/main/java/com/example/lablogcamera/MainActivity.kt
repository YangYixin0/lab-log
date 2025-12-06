package com.example.lablogcamera

import android.Manifest
import android.annotation.SuppressLint
import android.app.Application
import android.app.Activity
import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CameraManager
import android.graphics.Rect
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.util.Rational
import android.util.Size as AndroidSize
import android.view.Surface
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.camera.core.Camera
import androidx.camera.core.CameraControl
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.UseCaseGroup
import androidx.camera.core.ViewPort
import androidx.camera.core.AspectRatio
import androidx.camera.camera2.interop.Camera2Interop
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.lablogcamera.ui.theme.LabLogCameraTheme
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.max
import kotlin.math.min
import java.util.concurrent.Executors
import androidx.camera.core.Preview as CameraXPreview
import androidx.compose.ui.tooling.preview.Preview as ComposablePreview

private const val TAG = "LabLogCamera"

//region 通信协议相关数据类
/**
 * 服务器下发的命令统一抽象：
 * - command: 字符串命令类型，例如 "start_capture" / "stop_capture"
 * - payload: 可选负载，具体结构由 command 决定
 */
data class ServerCommand(val command: String, val payload: CommandPayload? = null)

/**
 * start_capture 命令的负载格式：
 * - format: 当前仅支持 "h264"
 * - aspectRatio: 目标宽高比（width:height，例如 4:3）
 * - bitrate: 目标码率（MB，例如 4 表示 4MB = 4,000,000 bps）
 * - fps: 期望帧率，0 或 null 表示不限（由设备尽可能多发）
 */
data class CommandPayload(
    val format: String,
    val aspectRatio: AspectRatio,
    val bitrate: Int,  // In MB, will be converted to bps
    val fps: Int? = null
)

data class AspectRatio(val width: Int, val height: Int)

/**
 * 发送给服务器的状态消息：
 * - status: "ready" / "capture_started" / "capture_stopped" / "error" 等
 * - message: 用于人类阅读的详细说明
 */
data class ClientStatus(
    val status: String,
    val message: String? = null,
    val rotation: Int? = null  // 设备旋转角度，后端可用于旋转视频
)

/**
 * 编码后的单帧 H.264 数据，携带设备侧时间戳（毫秒）
 * 时间戳会被打包进二进制帧头，供后端重建时间轴 / 估算 FPS。
 */
data class EncodedFrame(val data: ByteArray, val timestampMs: Long)

data class ResolutionOption(
    val width: Int,
    val height: Int,
    val format: String,
    val lensFacing: String
)

data class ClientCapabilities(
    val type: String = "capabilities",
    val deviceModel: String,
    val sdkInt: Int,
    val resolutions: List<ResolutionOption>
)
//endregion

//region H.264 编码器封装
/**
 * 对 Android 平台的 MediaCodec 进行简单封装：
 * - 通过 start() 进行一次性配置（分辨率 / 码率 / 目标帧率）
 * - encode() 接收 CameraX 的 ImageProxy，完成 YUV->NV12 转换并送入编码器
 * - 编码输出通过回调 onFrameEncoded 向外传递
 */
class H264Encoder(private val onFrameEncoded: (EncodedFrame) -> Unit) {

    private var mediaCodec: MediaCodec? = null

    fun start(width: Int, height: Int, bitrate: Int, targetFps: Int) {
        // MediaCodec 的帧率设置主要给编码器内部参考；真实发送帧率由上层 Analyzer 控制
        val frameRate = if (targetFps > 0) targetFps else 10
        val mediaFormat = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height).apply {
            // 使用标准 YUV420 半平面格式（NV12），搭配 toNV12ByteArray() 转换
            setInteger(
                MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar
            )
            setInteger(MediaFormat.KEY_BIT_RATE, bitrate)
            setInteger(MediaFormat.KEY_FRAME_RATE, frameRate)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1) // Key frame every second
        }
        Log.d(TAG, "Encoder config: ${width}x${height}")

        try {
            mediaCodec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC).apply {
                configure(mediaFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                start()
            }
            Log.d(TAG, "H.264 Encoder started successfully")
        } catch (e: IOException) {
            Log.e(TAG, "Failed to create H.264 encoder", e)
        }
    }

    @SuppressLint("UnsafeOptInUsageError")
    fun encode(image: ImageProxy, cropRect: Rect) {
        val codec = mediaCodec ?: return
        try {
            // 将整帧转换和编码过程都放在 try 中，防止异常向外抛出导致 Analyzer 中断
            val yuvBytes = image.toNv12ByteArray(cropRect)

            val inputBufferIndex = codec.dequeueInputBuffer(10000) // 10ms timeout
            if (inputBufferIndex >= 0) {
                val inputBuffer = codec.getInputBuffer(inputBufferIndex)
                if (inputBuffer != null) {
                    inputBuffer.clear()
                    // 安全检查：避免帧数据大于编码器输入缓冲区导致 BufferOverflow
                    if (inputBuffer.capacity() < yuvBytes.size) {
                        Log.e(TAG, "Encoder input buffer too small: cap=${inputBuffer.capacity()}, frame=${yuvBytes.size}")
                        return
                    }
                    inputBuffer.put(yuvBytes)
                }
                val presentationTimeUs = image.imageInfo.timestamp / 1000L
                codec.queueInputBuffer(inputBufferIndex, 0, yuvBytes.size, presentationTimeUs, 0)
            }

            val bufferInfo = MediaCodec.BufferInfo()
            var outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
            while (outputBufferIndex >= 0) {
                val outputBuffer = codec.getOutputBuffer(outputBufferIndex)
                if (outputBuffer != null && bufferInfo.size > 0) {
                    val encodedData = ByteArray(bufferInfo.size)
                    outputBuffer.get(encodedData)
                    // 使用编码器输出的时间戳作为“设备时间”，与原始图像时间基本一致
                    val timestampMs = bufferInfo.presentationTimeUs / 1000L
                    onFrameEncoded(EncodedFrame(encodedData, timestampMs))
                }
                codec.releaseOutputBuffer(outputBufferIndex, false)
                outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
            }
        } catch (e: Exception) {
            Log.e(TAG, "H.264 encoding error", e)
        }
    }

    fun stop() {
        try {
            mediaCodec?.stop()
            mediaCodec?.release()
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping encoder", e)
        }
        mediaCodec = null
        Log.d(TAG, "H.264 Encoder stopped.")
    }
}

private fun Rect.ensureEvenBounds(maxWidth: Int, maxHeight: Int): Rect {
    var left = this.left.coerceIn(0, maxWidth - 2)
    var top = this.top.coerceIn(0, maxHeight - 2)
    if (left % 2 != 0) left -= 1
    if (top % 2 != 0) top -= 1
    var right = this.right.coerceIn(left + 2, maxWidth)
    var bottom = this.bottom.coerceIn(top + 2, maxHeight)
    var width = right - left
    var height = bottom - top
    if (width % 2 != 0) {
        right -= 1
        width -= 1
    }
    if (height % 2 != 0) {
        bottom -= 1
        height -= 1
    }
    return Rect(left, top, right, bottom)
}
//endregion

// ViewModel：负责 WebSocket 生命周期管理 + CameraX 分析与编码控制
class WebSocketViewModel(application: Application) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(WebSocketUiState())
    val uiState: StateFlow<WebSocketUiState> = _uiState.asStateFlow()

    /**
     * 当前 UI 选择的宽高比（默认 4:3）。
     * - 当服务器下发带 aspectRatio 的 start_capture 时，会覆盖为服务器指定的宽高比；
     * - 当服务器发送纯 \"start\"（不含 aspectRatio）时，将按此处用户选择的宽高比进行采集。
     */
    private val _selectedAspectRatio = MutableStateFlow(Rational(4, 3))
    val selectedAspectRatio: StateFlow<Rational> = _selectedAspectRatio.asStateFlow()

    /**
     * 当前 UI 选择的摄像头（默认后置）。
     */
    private val _selectedCameraFacing = MutableStateFlow(CameraCharacteristics.LENS_FACING_BACK)
    val selectedCameraFacing: StateFlow<Int> = _selectedCameraFacing.asStateFlow()

    // 最近一帧的旋转角度（来自 ImageProxy.imageInfo.rotationDegrees），用于 UI 虚线框方向判断
    private val _lastRotationDegrees = MutableStateFlow(0)
    val lastRotationDegrees: StateFlow<Int> = _lastRotationDegrees.asStateFlow()

    // 录制时锁定的旋转角度（用于虚线框保持不变），未录制时为 null
    private val _lockedOverlayRotation = MutableStateFlow<Int?>(null)
    val lockedOverlayRotation: StateFlow<Int?> = _lockedOverlayRotation.asStateFlow()

    // 设备物理方向（来自 OrientationEventListener，0=竖放, 90=右横, 180=倒置, 270=左横）
    private val _devicePhysicalRotation = MutableStateFlow(0)
    
    // 更新设备物理方向（从 MainContent 的 OrientationEventListener 调用）
    fun updateDevicePhysicalRotation(rotation: Int) {
        _devicePhysicalRotation.value = rotation
    }

    private val client = OkHttpClient()
    private var webSocket: WebSocket? = null
    private var h264Encoder: H264Encoder? = null
    private var encoderStarted: Boolean = false
    private var encoderBitrate: Int = 2_000_000
    // 录制时锁定的裁剪区域，避免会话期间尺寸变化导致编码器问题
    private var lockedCropRect: Rect? = null
    // 记录上一次裁剪时的“是否纵向”状态，用于旋转方向切换时重置裁剪框
    private var lastCropOrientationPortrait: Boolean? = null
    var requestedAspectRatio: Rational? = null
        private set
    // 用于向后兼容和日志显示
    var requestedWidth: Int = 0
        private set
    var requestedHeight: Int = 0
        private set
    private var requestedFps: Int = 0
    private var lastFrameSentTimeNs: Long = 0L
    private var droppedFrames: Int = 0
    private val cameraManager: CameraManager? =
        application.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
    private var cachedCapabilitiesJson: String? = null
    // 缓存 ImageAnalysis 的实际分辨率（按摄像头分别缓存，在首次采集时记录）
    private var cachedImageAnalysisResolution: MutableMap<Int, AndroidSize> = mutableMapOf()

    val imageAnalysis = mutableStateOf<ImageAnalysis?>(null)
    private val cameraExecutor = Executors.newSingleThreadExecutor()

    private fun applyRotateAndCrop(extender: Camera2Interop.Extender<*>) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                extender.setCaptureRequestOption(
                    CaptureRequest.SCALER_ROTATE_AND_CROP,
                    CaptureRequest.SCALER_ROTATE_AND_CROP_AUTO
                )
                Log.d(TAG, "SCALER_ROTATE_AND_CROP set to AUTO")
            } catch (e: Exception) {
                Log.w(TAG, "Failed to set SCALER_ROTATE_AND_CROP", e)
            }
        }
    }

    /**
     * 当用户在主界面切换宽高比选项（4:3 / 16:9 / 不裁剪）时调用。
     */
    fun onAspectRatioSelected(width: Int, height: Int) {
        val safeWidth = width.coerceAtLeast(1)
        val safeHeight = height.coerceAtLeast(1)
        _selectedAspectRatio.value = Rational(safeWidth, safeHeight)
    }

    /**
     * 当用户在主界面切换摄像头选项（后置/前置）时调用。
     */
    fun onCameraFacingSelected(facing: Int) {
        if (facing != CameraCharacteristics.LENS_FACING_BACK && 
            facing != CameraCharacteristics.LENS_FACING_FRONT) {
            return
        }
        _selectedCameraFacing.value = facing
    }

    /**
     * 获取硬件支持的最高分辨率（用于 ImageAnalysis）。
     * 尝试使用硬件支持的最高分辨率，以获得更大的 FOV。
     */
    private fun getMaxSupportedResolution(facing: Int = CameraCharacteristics.LENS_FACING_BACK): AndroidSize {
        val manager = cameraManager ?: return AndroidSize(1920, 1920) // 默认回退
        return try {
            var maxSize = AndroidSize(1920, 1920) // 默认值
            var maxArea = 0L

            manager.cameraIdList?.forEach { cameraId ->
                val characteristics = manager.getCameraCharacteristics(cameraId)
                val lensFacing = characteristics.get(CameraCharacteristics.LENS_FACING)
                // 查询指定方向的摄像头
                if (lensFacing == facing) {
                    val streamMap = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                    val sizes = streamMap?.getOutputSizes(ImageFormat.YUV_420_888) ?: emptyArray()
                    sizes.forEach { size ->
                        val area = size.width.toLong() * size.height.toLong()
                        if (area > maxArea) {
                            maxArea = area
                            maxSize = size
                        }
                    }
                }
            }

            Log.d(TAG, "Max supported resolution for ImageAnalysis (facing=$facing): ${maxSize.width}x${maxSize.height}")
            maxSize
        } catch (e: Exception) {
            Log.e(TAG, "Failed to get max supported resolution for facing=$facing", e)
            AndroidSize(1920, 1920) // 默认回退
        }
    }

    fun onUrlChange(newUrl: String) {
        _uiState.update { it.copy(url = newUrl) }
    }

    fun onConnectToggle(shouldConnect: Boolean) {
        if (shouldConnect) connect() else disconnect()
    }

    /**
     * 更新用于虚线框显示的旋转：
     * - 未录制时，实时跟随图像旋转
     * - 开始录制时锁定当前旋转，录制期间不再变化
     */
    fun updateOverlayRotation(rotationDegrees: Int) {
        val norm = when ((rotationDegrees % 360 + 360) % 360) {
            90, 180, 270 -> (rotationDegrees % 360 + 360) % 360
            else -> 0
        }
        if (_uiState.value.isStreaming) {
            if (_lockedOverlayRotation.value == null) {
                _lockedOverlayRotation.value = norm
            }
        } else {
            _lockedOverlayRotation.value = null
            _lastRotationDegrees.value = norm
        }
    }

    /**
     * 在开始录制时锁定当前旋转，结束录制后恢复实时更新
     */
    fun lockOverlayRotationOnStart() {
        if (_lockedOverlayRotation.value == null) {
            _lockedOverlayRotation.value = _lastRotationDegrees.value
        }
    }

    fun unlockOverlayRotationOnStop() {
        _lockedOverlayRotation.value = null
    }

    /**
     * 根据设备物理旋转和摄像头类型计算后端需要的 rotation 值。
     * - 后置摄像头：rotationForBackend = (physicalRotation + 90) % 360
     * - 前置摄像头：
     *   - 竖放（0°）或倒放（180°）：rotationForBackend = (physicalRotation + 90 + 180) % 360
     *   - 左横（270°）或右横（90°）：rotationForBackend = (physicalRotation + 90) % 360
     */
    private fun calculateRotationForBackend(physicalRotation: Int, cameraFacing: Int): Int {
        return when (cameraFacing) {
            CameraCharacteristics.LENS_FACING_FRONT -> {
                // 前置摄像头：竖放或倒放时需要额外加180°，横放时不需要
                if (physicalRotation == 0 || physicalRotation == 180) {
                    (physicalRotation + 90 + 180) % 360
                } else {
                    (physicalRotation + 90) % 360
                }
            }
            else -> (physicalRotation + 90) % 360
        }
    }

    /**
     * 初始化临时 ImageAnalysis 以获取实际分辨率（在权限获取后或切换摄像头后调用）。
     * 捕获第一帧后立即清理，不影响正常采集流程。
     */
    fun initializeImageAnalysisResolution(context: Context, lifecycleOwner: LifecycleOwner) {
        val facing = _selectedCameraFacing.value
        if (cachedImageAnalysisResolution.containsKey(facing)) {
            // 该摄像头已经获取过，不需要重复
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
                val cameraProvider = cameraProviderFuture.get()
                val maxResolution = getMaxSupportedResolution(facing)
                
                val tempAnalysis = ImageAnalysis.Builder()
                    .setTargetResolution(maxResolution)
                    .setTargetRotation(Surface.ROTATION_0)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                
                var frameReceived = false
                tempAnalysis.setAnalyzer(cameraExecutor) { imageProxy ->
                    if (!frameReceived) {
                        frameReceived = true
                        cachedImageAnalysisResolution[facing] = AndroidSize(imageProxy.width, imageProxy.height)
                        Log.d(TAG, "Initialized ImageAnalysis resolution for facing=$facing: ${imageProxy.width}x${imageProxy.height}")
                        // 立即清理，避免影响正常流程
                        tempAnalysis.clearAnalyzer()
                        viewModelScope.launch(Dispatchers.Main) {
                            cameraProvider.unbind(tempAnalysis)
                        }
                    }
                    imageProxy.close()
                }
                
                val cameraSelector = when (facing) {
                    CameraCharacteristics.LENS_FACING_FRONT -> CameraSelector.DEFAULT_FRONT_CAMERA
                    else -> CameraSelector.DEFAULT_BACK_CAMERA
                }
                withContext(Dispatchers.Main) {
                    cameraProvider.bindToLifecycle(lifecycleOwner, cameraSelector, tempAnalysis)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to initialize ImageAnalysis resolution for facing=$facing", e)
                // 如果失败，使用预期分辨率
                cachedImageAnalysisResolution[facing] = getMaxSupportedResolution(facing)
            }
        }
    }

    private fun connect() {
        if (webSocket != null) return

        val request = Request.Builder().url(_uiState.value.url).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                _uiState.update { it.copy(isConnected = true, statusMessage = "Connected, ready for command") }
                sendStatus(ClientStatus("ready", "Client is ready to stream"))
                // 连接建立后立即上报自身能力（分辨率列表等），便于服务器做决策
                sendCapabilities()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "<-- Received command: $text")
                handleServerCommand(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                _uiState.update { it.copy(isConnected = false, isStreaming = false, statusMessage = "Error: ${t.message}") }
                stopStreaming()
                this@WebSocketViewModel.webSocket = null
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                _uiState.update { it.copy(isConnected = false, isStreaming = false, statusMessage = "Disconnected") }
                stopStreaming()
                this@WebSocketViewModel.webSocket = null
            }
        })
    }

    private fun handleServerCommand(commandStr: String) {
        try {
            val obj = JSONObject(commandStr)
            when (obj.optString("command")) {
                "start_capture" -> {
                    val payload = obj.optJSONObject("payload")
                    if (payload != null) {
                        // 解析宽高比（例如 4:3）：
                        // - 如果服务器下发了 aspectRatio，则强制使用服务器宽高比，并同步更新本地 selectedAspectRatio；
                        // - 如果未下发 aspectRatio（纯 \"start\"），则使用当前 UI 选择的宽高比。
                        val aspectRatioObj = payload.optJSONObject("aspectRatio")
                        val aspectRatio: Rational = if (aspectRatioObj != null) {
                            val aspectWidth = aspectRatioObj.optInt("width", 4).coerceAtLeast(1)
                            val aspectHeight = aspectRatioObj.optInt("height", 3).coerceAtLeast(1)
                            val serverRatio = Rational(aspectWidth, aspectHeight)
                            // 服务器显式指定宽高比时，覆盖本地选择并同步到 UI
                            _selectedAspectRatio.value = serverRatio
                            serverRatio
                        } else {
                            // 服务器未指定宽高比：使用当前 UI 选择的宽高比
                            selectedAspectRatio.value
                        }

                        // 解析码率（MB），转换为 bps
                        val bitrateMb = payload.optInt("bitrate", 4) // 默认 4 MB
                        val bitrateBps = bitrateMb * 1_000_000 // 转换为 bps

                        // fps 缺省或为 0 时表示“不限制帧率”，Analyzer 尽可能多发
                        val fps = payload.optInt("fps", 0)
                        startStreaming(aspectRatio, bitrateBps, fps)
                    } else {
                        Log.w(TAG, "start_capture payload missing, ignoring")
                    }
                }
                "stop_capture" -> stopStreaming()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to parse command", e)
            sendStatus(ClientStatus("error", "Invalid command received: $commandStr"))
        }
    }

    private fun startStreaming(aspectRatio: Rational, bitrate: Int, fps: Int) {
        if (_uiState.value.isStreaming) return

        viewModelScope.launch(Dispatchers.IO) {
            try {
                requestedAspectRatio = aspectRatio
                // 为了向后兼容和日志显示，计算一个示例分辨率（基于宽高比）
                // 使用常见的宽度作为基准，例如 1920
                val baseWidth = 1920
                val calculatedHeight = (baseWidth * aspectRatio.denominator / aspectRatio.numerator).let { h ->
                    // 确保高度为偶数
                    if (h % 2 == 0) h else h - 1
                }
                requestedWidth = baseWidth
                requestedHeight = calculatedHeight

                encoderBitrate = bitrate
                // 记录服务器期望的帧率；负数一律归零（视为不限）
                requestedFps = fps.coerceAtLeast(0)
                lastFrameSentTimeNs = 0L
                droppedFrames = 0
                encoderStarted = false

                var frameSequence = 0L
                h264Encoder = H264Encoder { encodedFrame ->
                    if (_uiState.value.isConnected) {
                        val payload = encodedFrame.data
                        val headerSize = 16
                        // 自定义帧头（二进制）：
                        // [0..7]   int64  timestampMs（设备时间）
                        // [8..11]  int32  frameSequence（低 32 位递增序号）
                        // [12..15] int32  payload.size（后续 H.264 数据长度）
                        val buffer = ByteBuffer.allocate(headerSize + payload.size).order(ByteOrder.BIG_ENDIAN)
                        buffer.putLong(encodedFrame.timestampMs)
                        buffer.putInt((frameSequence and 0xFFFFFFFF).toInt())
                        buffer.putInt(payload.size)
                        buffer.put(payload)
                        frameSequence = (frameSequence + 1) and 0xFFFFFFFFL
                        webSocket?.send(buffer.array().toByteString())
                    }
                }

                // 获取显示旋转，确保 ImageAnalysis 和 Preview 使用相同的旋转
                val windowManager = getApplication<Application>().getSystemService(Context.WINDOW_SERVICE) as? WindowManager
                val displayRotation = windowManager?.defaultDisplay?.rotation ?: Surface.ROTATION_0
                val targetRotation = when (displayRotation) {
                    Surface.ROTATION_0 -> Surface.ROTATION_0
                    Surface.ROTATION_90 -> Surface.ROTATION_90
                    Surface.ROTATION_180 -> Surface.ROTATION_180
                    Surface.ROTATION_270 -> Surface.ROTATION_270
                    else -> Surface.ROTATION_0
                }

                // 这里不再让 CameraX 按宽高比自行选分辨率，而是：
                // 1. 使用 CameraCharacteristics 查询后置相机支持的 YUV_420_888 的最大分辨率；
                // 2. 用 setTargetResolution() 明确要求 ImageAnalysis 使用这个最大分辨率；
                // 3. 再由 computeCropRect() 按服务器指定的宽高比（例如 4:3 / 16:9）进行裁剪。
                //
                // 这样可以保证：
                // - ImageAnalysis 始终以设备允许的最高分辨率工作（FOV 最大）；
                // - 服务器看到的编码分辨率严格按命令宽高比（例如 4:3 时得到 1920x1440，而不是 640x480）。
                val currentFacing = _selectedCameraFacing.value
                val maxResolution = getMaxSupportedResolution(currentFacing)
                Log.d(
                    TAG,
                    "ImageAnalysis targetResolution (max, facing=$currentFacing): ${maxResolution.width}x${maxResolution.height}, requestedAspectRatio=${aspectRatio.numerator}:${aspectRatio.denominator}"
                )

                val analysisBuilder = ImageAnalysis.Builder()
                    .setTargetResolution(maxResolution) // 始终请求硬件支持的最大 YUV_420_888 分辨率
                    .setTargetRotation(Surface.ROTATION_0) // 固定 0，避免 HAL 旋转叠加导致的平面错位
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)

                // 暂停 HAL 级旋转裁剪，先验证纯手动裁剪 + 固定旋转 0 是否消除条纹/绿带
                // applyRotateAndCrop(Camera2Interop.Extender(analysisBuilder))

                val analysis = analysisBuilder
                    .build()
                    .apply {
                        setAnalyzer(cameraExecutor) { imageProxy ->
                            try {
                                // 记录 ImageAnalysis 实际提供的分辨率（仅首次）
                                if (!encoderStarted) {
                                    val currentFacing = _selectedCameraFacing.value
                                    Log.d(TAG, "ImageAnalysis actual resolution (facing=$currentFacing): ${imageProxy.width}x${imageProxy.height} (target aspectRatio: ${aspectRatio.numerator}:${aspectRatio.denominator})")
                                    // 缓存实际分辨率，用于后续连接时上报
                                    cachedImageAnalysisResolution[currentFacing] = AndroidSize(imageProxy.width, imageProxy.height)
                                }

                                val encoder = h264Encoder
                                if (encoder != null) {
                                    val rotationDegrees = imageProxy.imageInfo.rotationDegrees
                                    // 记录最近一次旋转，用于 UI 虚线框方向（未录制时实时更新，录制时锁定）
                                    updateOverlayRotation(rotationDegrees)
                                    val isPortrait = rotationDegrees % 180 != 0
                                    // 当设备从横向切换到纵向（或反之）时，重置裁剪区域以匹配新的宽高比方向
                                    if (lockedCropRect != null && lastCropOrientationPortrait != null && lastCropOrientationPortrait != isPortrait) {
                                        lockedCropRect = null
                                        Log.d(TAG, "Orientation axis changed, reset lockedCropRect")
                                    }
                                    lastCropOrientationPortrait = isPortrait

                                    // 基础宽高比：服务器请求或默认 4:3；纵向时翻转为 3:4
                                    val baseAspectRatio = (requestedAspectRatio ?: Rational(4, 3)).let {
                                        val safeDenominator = if (it.denominator == 0) 1 else it.denominator
                                        Rational(it.numerator, safeDenominator)
                                    }
                                    val aspectForCrop = if (isPortrait) {
                                        Rational(baseAspectRatio.denominator, baseAspectRatio.numerator)
                                    } else {
                                        baseAspectRatio
                                    }
                                    val targetFps = requestedFps
                                    // 基于服务器给出的目标 FPS 主动丢帧：
                                    // - targetFps <= 0：不过滤，所有帧都尝试编码发送
                                    // - targetFps > 0：按时间间隔丢弃多余帧，平滑控制发送速率
                                    val shouldSend = shouldSendFrame(targetFps)
                                    if (shouldSend) {
                                    val desiredAspect = requestedAspectRatio ?: Rational(4, 3)
                                    val physicalRotation = _devicePhysicalRotation.value
                                    val isPortraitByPhysical = physicalRotation % 180 == 0
                                    // 安全尺寸裁剪：根据选择的宽高比选择接近的安全尺寸；竖屏/横屏分别取对齐值
                                    val cropRect = lockedCropRect ?: computeSafeAlignedRect(
                                        imageProxy,
                                        desiredAspect,
                                        isPortraitByPhysical
                                    ).also {
                                            lockedCropRect = it
                                            Log.d(TAG, "Locked crop rect: ${it.width()}x${it.height()}, rotation=$rotationDegrees")
                                        }
                                        val frameWidth = cropRect.width()
                                        val frameHeight = cropRect.height()
                                        if (!encoderStarted) {
                                            // 以"裁剪后尺寸"初始化编码器
                                            encoder.start(frameWidth, frameHeight, encoderBitrate, targetFps)
                                            encoderStarted = true
                                            val physicalRotation = _devicePhysicalRotation.value
                                            val currentFacing = _selectedCameraFacing.value
                                            val rotationForBackend = calculateRotationForBackend(physicalRotation, currentFacing)
                                            Log.d(TAG, "H.264 Encoder started: ${frameWidth}x${frameHeight}, physicalRotation=$physicalRotation, cameraFacing=$currentFacing, imageRotation=$rotationDegrees, rotationForBackend=$rotationForBackend")
                                        }
                                        encoder.encode(imageProxy, cropRect)
                                    } else if (targetFps > 0) {
                                        droppedFrames++
                                        if (droppedFrames <= 5 || droppedFrames % targetFps == 0) {
                                            Log.v(TAG, "Frame dropped to honor ${targetFps}fps target (dropped=$droppedFrames)")
                                        }
                                    }
                                }
                            } catch (e: Exception) {
                                Log.e(TAG, "Analyzer error while encoding frame", e)
                            } finally {
                                imageProxy.close()
                            }
                        }
                    }
                withContext(Dispatchers.Main) {
                    imageAnalysis.value = analysis
                }

                val fpsLabel = formatFpsLabel(requestedFps)
                val bitrateMb = encoderBitrate / 1_000_000
                val statusMsg = "Streaming H.264 at ${aspectRatio.numerator}:${aspectRatio.denominator} aspect ratio, ${bitrateMb}MB bitrate ($fpsLabel)"
                _uiState.update { it.copy(isStreaming = true, statusMessage = statusMsg) }
                // 发送 capture_started 状态，包含当前设备旋转角度，后端可用于旋转视频
                // 根据摄像头类型计算正确的 rotation（使用之前声明的 currentFacing）
                val physicalRotation = _devicePhysicalRotation.value
                val rotationForBackend = calculateRotationForBackend(physicalRotation, currentFacing)
                Log.d(TAG, "Sending capture_started: physicalRotation=$physicalRotation, cameraFacing=$currentFacing, rotationForBackend=$rotationForBackend")
                sendStatus(ClientStatus("capture_started", statusMsg, rotationForBackend))

            } catch (e: Exception) {
                Log.e(TAG, "Failed to start streaming", e)
                _uiState.update { it.copy(isStreaming = false, statusMessage = "Error starting stream") }
                sendStatus(ClientStatus("error", "Failed to start stream: ${e.message}"))
            }
        }
    }

    private fun stopStreaming() {
        if (!_uiState.value.isStreaming && imageAnalysis.value == null) return

        viewModelScope.launch(Dispatchers.IO) {
            withContext(Dispatchers.Main) {
                imageAnalysis.value?.clearAnalyzer()
                imageAnalysis.value = null
            }
            h264Encoder?.stop()
            h264Encoder = null
            encoderStarted = false
            lockedCropRect = null  // 清除锁定的裁剪区域
            lastCropOrientationPortrait = null
            requestedAspectRatio = null
            requestedFps = 0
            lastFrameSentTimeNs = 0L
            droppedFrames = 0

            _uiState.update { it.copy(isStreaming = false, statusMessage = "Stream stopped") }
            if(_uiState.value.isConnected) {
                sendStatus(ClientStatus("capture_stopped", "Streaming has been stopped by client/server."))
            }
        }
    }

    private fun sendStatus(status: ClientStatus) {
        if (!_uiState.value.isConnected) return
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val statusJson = JSONObject().apply {
                    put("status", status.status)
                    status.message?.let { put("message", it) }
                    status.rotation?.let { put("rotation", it) }
                }.toString()
                webSocket?.send(statusJson)
                Log.d(TAG, "--> Sent status: $statusJson")
            } catch (e: Exception) {
                Log.e(TAG, "Failed to send status", e)
            }
        }
    }

    private fun sendCapabilities() {
        if (!_uiState.value.isConnected) return
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val capabilitiesJson = cachedCapabilitiesJson ?: buildCapabilitiesJson()
                cachedCapabilitiesJson = capabilitiesJson
                if (capabilitiesJson.isNotEmpty()) {
                    webSocket?.send(capabilitiesJson)
                    Log.d(TAG, "--> Sent capabilities: $capabilitiesJson")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to send capabilities", e)
            }
        }
    }

    private fun buildCapabilitiesJson(): String {
        val manager = cameraManager ?: return ""
        return try {
            val resolutionList = mutableListOf<ResolutionOption>()
            manager.cameraIdList?.forEach { cameraId ->
                val characteristics = manager.getCameraCharacteristics(cameraId)
                val lensFacing = characteristics.get(CameraCharacteristics.LENS_FACING)
                val lensName = when (lensFacing) {
                    CameraCharacteristics.LENS_FACING_FRONT -> "front"
                    CameraCharacteristics.LENS_FACING_EXTERNAL -> "external"
                    else -> "back"
                }
                val streamMap = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                val sizes = streamMap?.getOutputSizes(ImageFormat.YUV_420_888) ?: emptyArray()
                sizes.forEach { size ->
                    resolutionList += ResolutionOption(
                        width = size.width,
                        height = size.height,
                        format = "YUV_420_888",
                        lensFacing = lensName
                    )
                }
            }
            val sorted = resolutionList
                .distinctBy { Triple(it.width, it.height, it.lensFacing) }
                .sortedByDescending { it.width * it.height }
            // 按面积从大到小排序后上报，方便后端优先选择高分辨率
            val array = JSONArray()
            sorted.forEach {
                array.put(
                    JSONObject()
                        .put("width", it.width)
                        .put("height", it.height)
                        .put("format", it.format)
                        .put("lensFacing", it.lensFacing)
                )
            }
            val currentFacing = _selectedCameraFacing.value
            val imageAnalysisRes = cachedImageAnalysisResolution[currentFacing] 
                ?: getMaxSupportedResolution(currentFacing)
            val capabilitiesObj = JSONObject()
                .put("type", "capabilities")
                .put("deviceModel", Build.MODEL ?: "unknown")
                .put("sdkInt", Build.VERSION.SDK_INT)
                .put("resolutions", array)
                .put("imageAnalysisResolution", JSONObject()
                    .put("width", imageAnalysisRes.width)
                    .put("height", imageAnalysisRes.height))
            capabilitiesObj.toString()
        } catch (e: SecurityException) {
            Log.e(TAG, "Unable to query camera characteristics", e)
            ""
        } catch (e: Exception) {
            Log.e(TAG, "Failed to build capabilities", e)
            ""
        }
    }

    private fun disconnect() {
        stopStreaming()
        webSocket?.close(1000, "User disconnected")
    }

    override fun onCleared() {
        super.onCleared()
        disconnect()
        cameraExecutor.shutdown()
    }

    private fun shouldSendFrame(targetFps: Int): Boolean {
        if (targetFps <= 0) {
            // 不限帧率：Analyzer 的每一帧都参与编码与发送
            return true
        }
        val nowNs = System.nanoTime()
        val minIntervalNs = 1_000_000_000L / targetFps
        if (lastFrameSentTimeNs == 0L || nowNs - lastFrameSentTimeNs >= minIntervalNs) {
            lastFrameSentTimeNs = nowNs
            return true
        }
        return false
    }

    private fun formatFpsLabel(fpsValue: Int): String {
        return if (fpsValue <= 0) "unlimited fps" else "${fpsValue}fps"
    }

    /**
     * 编码器对齐裁剪：按目标宽高比居中裁剪，基准宽 1920，32/偶数对齐。
     * 无论设备横竖，都使用同一横向比例，方向由 rotationForBackend 处理。
     * 1:1 时使用全帧（不裁剪），但做 32 对齐以避免条纹。
     */
    private fun computeSafeAlignedRect(imageProxy: ImageProxy, desiredAspect: Rational, isPortraitByPhysical: Boolean): Rect {
        val imageWidth = imageProxy.width
        val imageHeight = imageProxy.height
        
        // 1:1 时使用全帧，但做 32 对齐
        val is1by1 = desiredAspect.numerator == 1 && desiredAspect.denominator == 1
        if (is1by1) {
            // 全帧对齐：宽高分别向下对齐到 32 的倍数且为偶数
            var alignedWidth = (imageWidth / 32) * 32
            var alignedHeight = (imageHeight / 32) * 32
            if (alignedWidth < 2) alignedWidth = 2
            if (alignedHeight < 2) alignedHeight = 2
            if (alignedWidth % 2 != 0) alignedWidth -= 1
            if (alignedHeight % 2 != 0) alignedHeight -= 1
            return Rect(0, 0, alignedWidth, alignedHeight)
        }
        
        // 根据目标宽高比选择安全尺寸：
        // - 16:9 时，横屏 1920x1088，竖屏 1088x1920（32/偶数对齐）
        // - 其它（含 4:3）时，横屏 1920x1472，竖屏 1472x1920
        val is16by9 = isAspectApprox(desiredAspect, 16, 9)
        val targetW = when {
            is16by9 && !isPortraitByPhysical -> minOf(1920, imageWidth)
            is16by9 && isPortraitByPhysical -> minOf(1088, imageWidth)
            !is16by9 && !isPortraitByPhysical -> minOf(1920, imageWidth)
            else -> minOf(1472, imageWidth)
        }
        val targetH = when {
            is16by9 && !isPortraitByPhysical -> minOf(1088, imageHeight)
            is16by9 && isPortraitByPhysical -> minOf(1920, imageHeight)
            !is16by9 && !isPortraitByPhysical -> minOf(1472, imageHeight)
            else -> minOf(1920, imageHeight)
        }

        // 32/偶数对齐
        var cropW = (targetW / 32) * 32
        var cropH = (targetH / 32) * 32
        if (cropW < 2) cropW = 2
        if (cropH < 2) cropH = 2
        if (cropW % 2 != 0) cropW -= 1
        if (cropH % 2 != 0) cropH -= 1

        val left = ((imageWidth - cropW) / 2).coerceAtLeast(0)
        val top = ((imageHeight - cropH) / 2).coerceAtLeast(0)
        val right = (left + cropW).coerceAtMost(imageWidth)
        val bottom = (top + cropH).coerceAtMost(imageHeight)
        return Rect(left, top, right, bottom)
    }

    private fun isAspectApprox(r: Rational, num: Int, den: Int, tol: Float = 0.03f): Boolean {
        val ratio = r.numerator.toFloat() / r.denominator.coerceAtLeast(1)
        val target = num.toFloat() / den.coerceAtLeast(1)
        return kotlin.math.abs(ratio - target) <= tol
    }

    /**
     * 全帧对齐裁剪：不按宽高比裁剪，直接使用全帧并向下对齐到 64 的倍数，保证偶数。
     * 目的：排除手动裁剪/旋转引入的平面错位风险，专注验证条纹/绿带是否来自 UV 顺序或编码器。
     */
    private fun computeFullFrameAlignedRect(imageProxy: ImageProxy): Rect {
        val imageWidth = imageProxy.width
        val imageHeight = imageProxy.height
        // 向下对齐到 64，且保证至少 2 像素
        val alignedWidth = (imageWidth / 64) * 64
        val alignedHeight = (imageHeight / 64) * 64
        val safeWidth = alignedWidth.coerceAtLeast(2).let { if (it % 2 != 0) it - 1 else it }
        val safeHeight = alignedHeight.coerceAtLeast(2).let { if (it % 2 != 0) it - 1 else it }
        return Rect(0, 0, safeWidth, safeHeight)
    }
}

/**
 * 将 CameraX 的 YUV_420_888 三平面数据转换为 NV12（YUV420 半平面：Y + 交错 UV）。
 * 布局与 COLOR_FormatYUV420SemiPlanar 对应，可显著减少绿色/紫色色块等伪影。
 *
 * 注意：
 * - 仅对传入的 cropRect 区域进行裁剪与转换，保证输出分辨率与服务器期望一致；
 * - 所有坐标 / 宽高都强制为偶数，以满足很多硬件编码器对 UV 对齐的要求。
 */
@SuppressLint("UnsafeOptInUsageError")
fun ImageProxy.toNv12ByteArray(cropRect: Rect): ByteArray {
    val safeRect = cropRect.ensureEvenBounds(width, height)
    val cropWidth = safeRect.width()
    val cropHeight = safeRect.height()
    val ySize = cropWidth * cropHeight
    val uvSize = ySize / 2
    val nv12 = ByteArray(ySize + uvSize)

    val yPlane = planes[0]
    val yBuffer = yPlane.buffer.duplicate()
    val yRowStride = yPlane.rowStride
    var dstIndex = 0
    for (row in safeRect.top until safeRect.bottom) {
        val rowStart = row * yRowStride + safeRect.left
        yBuffer.position(rowStart)
        yBuffer.get(nv12, dstIndex, cropWidth)
        dstIndex += cropWidth
    }

    // 部分设备 YUV_420_888 的 U/V 平面顺序与预期相反，这里交换平面以测试是否能消除条纹/绿带
    val uPlane = planes[1]
    val vPlane = planes[2]
    val uBuffer = uPlane.buffer.duplicate()
    val vBuffer = vPlane.buffer.duplicate()
    val uRowStride = uPlane.rowStride
    val vRowStride = vPlane.rowStride
    val uPixelStride = uPlane.pixelStride
    val vPixelStride = vPlane.pixelStride

    val chromaLeft = safeRect.left / 2
    val chromaTop = safeRect.top / 2
    val chromaWidth = cropWidth / 2
    val chromaHeight = cropHeight / 2

    var uvDstIndex = ySize
    for (row in 0 until chromaHeight) {
        val uRowStart = (row + chromaTop) * uRowStride
        val vRowStart = (row + chromaTop) * vRowStride
        for (col in 0 until chromaWidth) {
            val uIndex = uRowStart + (col + chromaLeft) * uPixelStride
            val vIndex = vRowStart + (col + chromaLeft) * vPixelStride
            // 恢复 NV12 顺序（U 后 V），结合全帧对齐策略做对照测试
            nv12[uvDstIndex++] = uBuffer.get(uIndex)
            nv12[uvDstIndex++] = vBuffer.get(vIndex)
        }
    }
    return nv12
}

private fun surfaceRotationToDegrees(rotation: Int): Int = when (rotation) {
    Surface.ROTATION_0 -> 0
    Surface.ROTATION_90 -> 90
    Surface.ROTATION_180 -> 180
    Surface.ROTATION_270 -> 270
    else -> 0
}


data class WebSocketUiState(
    val url: String = "ws://pqzc1405495.bohrium.tech:50001/android-cam",
    val isConnected: Boolean = false,
    val isStreaming: Boolean = false,
    val statusMessage: String = "Disconnected"
)

@OptIn(ExperimentalPermissionsApi::class)
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            LabLogCameraTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    MainScreen(modifier = Modifier.padding(innerPadding))
                }
            }
        }
    }
}

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun MainScreen(modifier: Modifier = Modifier, webSocketViewModel: WebSocketViewModel = viewModel()) {
        val cameraPermissionState = rememberPermissionState(Manifest.permission.CAMERA)
        val context = LocalContext.current
        val lifecycleOwner = LocalLifecycleOwner.current

    LaunchedEffect(Unit) {
        if (!cameraPermissionState.status.isGranted) {
                cameraPermissionState.launchPermissionRequest()
            }
                }

    // 权限获取后立即初始化 ImageAnalysis 分辨率
    LaunchedEffect(cameraPermissionState.status.isGranted) {
        if (cameraPermissionState.status.isGranted) {
            webSocketViewModel.initializeImageAnalysisResolution(context, lifecycleOwner)
        }
    }

    // 监听摄像头选择变化，切换时重新初始化分辨率
    val selectedCameraFacing by webSocketViewModel.selectedCameraFacing.collectAsState()
    LaunchedEffect(selectedCameraFacing) {
        if (cameraPermissionState.status.isGranted) {
            webSocketViewModel.initializeImageAnalysisResolution(context, lifecycleOwner)
        }
    }

        MainContent(
            modifier = modifier,
        webSocketViewModel = webSocketViewModel,
        cameraPermissionGranted = cameraPermissionState.status.isGranted
        )
}

@Composable
fun MainContent(
    modifier: Modifier = Modifier,
    webSocketViewModel: WebSocketViewModel = viewModel(),
    cameraPermissionGranted: Boolean
) {
    val uiState by webSocketViewModel.uiState.collectAsState()
    // 当前 UI 选择的宽高比（例如 4:3 / 16:9），用于本地预览和在服务器未指定时的默认采集宽高比
    val selectedAspectRatio by webSocketViewModel.selectedAspectRatio.collectAsState()
    val requestedAspect = webSocketViewModel.requestedAspectRatio
    val context = LocalContext.current
    val isStreaming = uiState.isStreaming
    
    // 使用 OrientationEventListener 检测设备物理旋转（即使 Activity 锁定方向也能检测）
    var deviceRotation by remember { mutableStateOf(0) }
    DisposableEffect(context) {
        val orientationListener = object : android.view.OrientationEventListener(context) {
            override fun onOrientationChanged(orientation: Int) {
                if (orientation == ORIENTATION_UNKNOWN) return
                // 将连续的方向角度转换为离散的旋转角度
                val rotation = when {
                    orientation >= 315 || orientation < 45 -> 0      // 竖向（正常）
                    orientation >= 45 && orientation < 135 -> 90     // 右横向
                    orientation >= 135 && orientation < 225 -> 180   // 倒置
                    orientation >= 225 && orientation < 315 -> 270   // 左横向
                    else -> 0
                }
                deviceRotation = rotation
                // 同时更新 ViewModel 中的物理方向状态，用于录制时决定是否需要旋转视频
                webSocketViewModel.updateDevicePhysicalRotation(rotation)
            }
        }
        if (orientationListener.canDetectOrientation()) {
            orientationListener.enable()
        }
        onDispose { orientationListener.disable() }
    }

    // 采集中保持亮屏，停止后恢复默认
    DisposableEffect(isStreaming) {
        val activity = context as? Activity
        if (isStreaming) {
            activity?.window?.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            activity?.window?.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        onDispose {
            activity?.window?.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // 相机预览区域：主界面顶部的正方形 Box，内部根据宽高比进行 FIT 预览
        if (cameraPermissionGranted) {
            BoxWithConstraints(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1f) // 固定为正方形区域
                    .background(Color.Black)
            ) {
                val density = LocalDensity.current
                // 检测设备当前是横向还是竖向（基于物理旋转）
                // 90 或 270 度为横放，0 或 180 度为竖放
                // 采集时锁定设备方向，不随旋转变化
                val lockedDeviceRotation = remember { mutableStateOf<Int?>(null) }
                LaunchedEffect(uiState.isStreaming) {
                    if (uiState.isStreaming && lockedDeviceRotation.value == null) {
                        lockedDeviceRotation.value = deviceRotation
                    } else if (!uiState.isStreaming) {
                        lockedDeviceRotation.value = null
                    }
                }
                val currentDeviceRotation = if (uiState.isStreaming && lockedDeviceRotation.value != null) {
                    lockedDeviceRotation.value!!
                } else {
                    deviceRotation
                }
                val isDeviceLandscape = (currentDeviceRotation == 90 || currentDeviceRotation == 270)
                
                // 根据设备方向调整虚线框的宽高比
                // 虚线框相对于重力方向始终显示为"横向"（宽大于高）
                // 设备竖放时：使用原始宽高比（如 16:9），虚线框在屏幕上为横向
                // 设备横放时：翻转宽高比（如 9:16），虚线框在屏幕上为竖向，但相对于重力仍为横向
                // 1:1 时无论设备横竖都显示为正方形
                val baseAspectRatio = (if (uiState.isStreaming) (requestedAspect ?: selectedAspectRatio) else selectedAspectRatio).let {
                    val safeDenominator = if (it.denominator == 0) 1 else it.denominator
                    Rational(it.numerator, safeDenominator)
                }
                val is1by1 = baseAspectRatio.numerator == 1 && baseAspectRatio.denominator == 1
                val overlayAspectRatio = if (is1by1) {
                    // 1:1 时无论设备横竖都显示为正方形
                    Rational(1, 1)
                } else if (isDeviceLandscape) {
                    // 设备横放时翻转宽高比
                    Rational(baseAspectRatio.denominator, baseAspectRatio.numerator)
                } else {
                    // 设备竖放时使用原始宽高比
                    baseAspectRatio
                }

                // 预览画面填满 Box（显示完整 ImageAnalysis 输出），再叠加虚线框标记实际采集比例区域
                CameraPreview(
                    viewModel = webSocketViewModel
                )

                Canvas(
                    modifier = Modifier
                        .fillMaxSize()
                        .clipToBounds()
                ) {
                    val boxWidthPx = size.width
                    val boxHeightPx = size.height
                    val ratio = overlayAspectRatio.numerator.toFloat() / overlayAspectRatio.denominator.toFloat()
                    val (frameWidthPx, frameHeightPx) = if (boxWidthPx / boxHeightPx > ratio) {
                        val h = boxHeightPx
                        val w = h * ratio
                        w to h
                    } else {
                        val w = boxWidthPx
                        val h = w / ratio
                        w to h
                    }
                    val left = (boxWidthPx - frameWidthPx) / 2f
                    val top = (boxHeightPx - frameHeightPx) / 2f

                    val strokeWidth = with(density) { 2.dp.toPx() }
                    val dash = with(density) { 6.dp.toPx() }
                    val gap = with(density) { 4.dp.toPx() }

                    drawRect(
                        color = Color.Black,
                        topLeft = Offset(left, top),
                        size = Size(frameWidthPx, frameHeightPx),
                        style = Stroke(
                            width = strokeWidth,
                            pathEffect = PathEffect.dashPathEffect(floatArrayOf(dash, gap))
                        )
                    )
                }
            }
        } else {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1f) // 固定为正方形区域
                    .background(Color.Gray),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "需要相机权限",
                    color = Color.White
                )
            }
        }

        Text(
            text = "虚线框内是真正采集的范围",
            color = Color.DarkGray,
            fontSize = 12.sp
        )

        // 摄像头选择控件（后置 / 前置）
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(text = "摄像头：")

            val selectedCameraFacing by webSocketViewModel.selectedCameraFacing.collectAsState()
            val isBackSelected = selectedCameraFacing == CameraCharacteristics.LENS_FACING_BACK
            val isFrontSelected = selectedCameraFacing == CameraCharacteristics.LENS_FACING_FRONT

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { webSocketViewModel.onCameraFacingSelected(CameraCharacteristics.LENS_FACING_BACK) },
                    enabled = !isBackSelected && !uiState.isStreaming
                ) {
                    Text("后置")
                }
                Button(
                    onClick = { webSocketViewModel.onCameraFacingSelected(CameraCharacteristics.LENS_FACING_FRONT) },
                    enabled = !isFrontSelected && !uiState.isStreaming
                ) {
                    Text("前置")
                }
            }
        }

        // 宽高比选择控件（4:3 / 16:9 / 不裁剪）
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(text = "宽高比：")

            val is43Selected = selectedAspectRatio.numerator == 4 && selectedAspectRatio.denominator == 3
            val is169Selected = selectedAspectRatio.numerator == 16 && selectedAspectRatio.denominator == 9
            val isNoCropSelected = selectedAspectRatio.numerator == 1 && selectedAspectRatio.denominator == 1

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { webSocketViewModel.onAspectRatioSelected(4, 3) },
                    enabled = !is43Selected && !uiState.isStreaming
                ) {
                    Text("4:3")
                }
                Button(
                    onClick = { webSocketViewModel.onAspectRatioSelected(16, 9) },
                    enabled = !is169Selected && !uiState.isStreaming
                ) {
                    Text("16:9")
                }
                Button(
                    onClick = { webSocketViewModel.onAspectRatioSelected(1, 1) },
                    enabled = !isNoCropSelected && !uiState.isStreaming
                ) {
                    Text("不裁剪")
                }
            }
        }

        Text("WebSocket URL:")
        TextField(
            value = uiState.url,
            onValueChange = { webSocketViewModel.onUrlChange(it) },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            enabled = !uiState.isConnected
        )

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(
                    modifier = Modifier
                        .size(12.dp)
                        .clip(CircleShape)
                        .background(if (uiState.isStreaming) Color.Green else Color.Gray)
                )
                Text(text = uiState.statusMessage)
            }
            Switch(
                checked = uiState.isConnected,
                onCheckedChange = { webSocketViewModel.onConnectToggle(it) }
            )
        }

        Text(
            text = "离开App或锁屏会中断视频采集",
            color = Color.Gray,
            style = androidx.compose.ui.text.TextStyle(fontSize = 12.sp, fontStyle = FontStyle.Italic)
        )
    }
}

@Composable
fun CameraPreview(
    viewModel: WebSocketViewModel = viewModel(),
    onResolutionChanged: (width: Int, height: Int) -> Unit = { _, _ -> }
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val context = LocalContext.current
    val imageAnalysis by viewModel.imageAnalysis
    val requestedAspectRatio = viewModel.requestedAspectRatio
    val requestedWidth = viewModel.requestedWidth
    val requestedHeight = viewModel.requestedHeight
    val selectedCameraFacing by viewModel.selectedCameraFacing.collectAsState()

    // 当宽高比变化时通知父组件更新预览区域宽高比
    LaunchedEffect(requestedAspectRatio) {
        if (requestedAspectRatio != null && requestedWidth > 0 && requestedHeight > 0) {
            onResolutionChanged(requestedWidth, requestedHeight)
        }
    }

    val previewView = remember {
        PreviewView(context).apply {
            // 使用 COMPATIBLE + FIT_CENTER，确保在正方形 Box 中完整显示 4:3 / 16:9 画面（可能出现黑边但不裁剪）
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
            scaleType = PreviewView.ScaleType.FIT_CENTER
            }
    }

    // 当 imageAnalysis、宽高比或摄像头选择变化时，重新绑定相机
    LaunchedEffect(imageAnalysis, requestedAspectRatio, selectedCameraFacing) {
        try {
            val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
                val cameraProvider = cameraProviderFuture.get()
                    cameraProvider.unbindAll()
                    val cameraSelector = when (selectedCameraFacing) {
                        CameraCharacteristics.LENS_FACING_FRONT -> CameraSelector.DEFAULT_FRONT_CAMERA
                        else -> CameraSelector.DEFAULT_BACK_CAMERA
                    }

            // 获取显示旋转，确保 Preview 和 ImageAnalysis 使用相同的旋转
            val displayRotation = previewView.display.rotation
            val targetRotation = when (displayRotation) {
                Surface.ROTATION_0 -> Surface.ROTATION_0
                Surface.ROTATION_90 -> Surface.ROTATION_90
                Surface.ROTATION_180 -> Surface.ROTATION_180
                Surface.ROTATION_270 -> Surface.ROTATION_270
                else -> Surface.ROTATION_0
            }

            val preview = CameraXPreview.Builder()
                .setTargetRotation(targetRotation)
                .build().also {
                        it.setSurfaceProvider(previewView.surfaceProvider)
                    }

            // 使用 ViewPort + UseCaseGroup 统一 Preview 和 ImageAnalysis 的 FOV
            // 创建 ViewPort，优先使用采集中实际生效的宽高比；如果尚未开始采集，则使用当前 UI 选中的宽高比
            val uiAspectRatio = viewModel.selectedAspectRatio.value
            val targetAspectRatio = requestedAspectRatio ?: uiAspectRatio
            val viewPort = ViewPort.Builder(
                targetAspectRatio,
                targetRotation // 使用与 Preview 和 ImageAnalysis 相同的旋转
            ).build()

            // 如果 ImageAnalysis 已创建，则在绑定前更新其 targetRotation 与 Preview 一致
            imageAnalysis?.targetRotation = targetRotation

            // 创建 UseCaseGroup
            val useCaseGroupBuilder = UseCaseGroup.Builder()
            useCaseGroupBuilder.addUseCase(preview)
            imageAnalysis?.let { useCaseGroupBuilder.addUseCase(it) }
            useCaseGroupBuilder.setViewPort(viewPort)
            val useCaseGroup = useCaseGroupBuilder.build()

            // 使用 UseCaseGroup 绑定，确保 Preview 和 ImageAnalysis 共享相同的裁剪窗口
            val camera = cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        cameraSelector,
                useCaseGroup
            )

            // 注意：CameraX 的默认 linearZoom 值就是 0.0（最小变焦，最大 FOV）
            // 测试发现 setLinearZoom(0.0) 与默认行为一致，而 setLinearZoom(1.0) 会得到很小的 FOV
            // 因此不需要显式设置，保持默认值即可
            // 如果需要更小的 FOV（放大），可以调用 camera.cameraControl.setLinearZoom(0.5f) 等值
            // try {
            //     val cameraControl: CameraControl = camera.cameraControl
            //     cameraControl.setLinearZoom(0.0f) // 默认值，无需设置
            // } catch (e: Exception) {
            //     Log.w(TAG, "Failed to set linear zoom", e)
            // }

            val aspectRatioStr = requestedAspectRatio?.let { "${it.numerator}:${it.denominator}" } ?: "default"
            Log.d(TAG, "Camera bound with imageAnalysis=${imageAnalysis != null}, aspectRatio=$aspectRatioStr")

                } catch (e: Exception) {
                    Log.e(TAG, "Use case binding failed", e)
                }
        }

    AndroidView(
        modifier = Modifier
            .fillMaxSize()
            .clipToBounds(),
        factory = { previewView }
    )
}

@ComposablePreview(showBackground = true)
@Composable
fun MainContentPreview() {
    LabLogCameraTheme {
        MainContent(cameraPermissionGranted = true)
    }
}
