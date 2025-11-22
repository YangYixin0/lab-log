package com.example.lablogcamera

import android.Manifest
import android.annotation.SuppressLint
import android.app.Application
import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.graphics.Rect
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.util.Size
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
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
 * - resolution: 目标编码分辨率（宽高）
 * - bitrate: 目标码率（bps）
 * - fps: 期望帧率，0 或 null 表示不限（由设备尽可能多发）
 */
data class CommandPayload(
    val format: String,
    val resolution: Resolution,
    val bitrate: Int,
    val fps: Int? = null
)

data class Resolution(val width: Int, val height: Int)

/**
 * 发送给服务器的状态消息：
 * - status: "ready" / "capture_started" / "capture_stopped" / "error" 等
 * - message: 用于人类阅读的详细说明
 */
data class ClientStatus(val status: String, val message: String? = null)

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
            // 使用标准 YUV420 半平面格式（NV12），搭配下面的 toNV12ByteArray() 转换，避免色块/偏色
            setInteger(
                MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar
            )
            setInteger(MediaFormat.KEY_BIT_RATE, bitrate)
            setInteger(MediaFormat.KEY_FRAME_RATE, frameRate)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1) // Key frame every second
        }

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
        mediaCodec?.let { codec ->
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
//endregion

// ViewModel：负责 WebSocket 生命周期管理 + CameraX 分析与编码控制
class WebSocketViewModel(application: Application) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(WebSocketUiState())
    val uiState: StateFlow<WebSocketUiState> = _uiState.asStateFlow()

    private val client = OkHttpClient()
    private var webSocket: WebSocket? = null
    private var h264Encoder: H264Encoder? = null
    private var encoderStarted: Boolean = false
    private var encoderBitrate: Int = 2_000_000
    private var requestedWidth: Int = 1600
    private var requestedHeight: Int = 1200
    private var requestedFps: Int = 0
    private var lastFrameSentTimeNs: Long = 0L
    private var droppedFrames: Int = 0
    private val cameraManager: CameraManager? =
        application.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
    private var cachedCapabilitiesJson: String? = null

    val imageAnalysis = mutableStateOf<ImageAnalysis?>(null)
    private val cameraExecutor = Executors.newSingleThreadExecutor()

    fun onUrlChange(newUrl: String) {
        _uiState.update { it.copy(url = newUrl) }
    }

    fun onConnectToggle(shouldConnect: Boolean) {
        if (shouldConnect) connect() else disconnect()
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
                        val resolutionObj = payload.optJSONObject("resolution")
                        val width = resolutionObj?.optInt("width", requestedWidth) ?: requestedWidth
                        val height = resolutionObj?.optInt("height", requestedHeight) ?: requestedHeight
                        val bitrate = payload.optInt("bitrate", encoderBitrate)
                        // fps 缺省或为 0 时表示“不限制帧率”，Analyzer 尽可能多发
                        val fps = payload.optInt("fps", 0)
                        startStreaming(width, height, bitrate, fps)
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

    private fun startStreaming(width: Int, height: Int, bitrate: Int, fps: Int) {
        if (_uiState.value.isStreaming) return

        viewModelScope.launch(Dispatchers.IO) {
            try {
                requestedWidth = width
                requestedHeight = height
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

                val analysis = ImageAnalysis.Builder()
                    .setTargetResolution(Size(width, height))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                    .apply {
                        setAnalyzer(cameraExecutor) { imageProxy ->
                            try {
                                val encoder = h264Encoder
                                if (encoder != null) {
                                    val targetFps = requestedFps
                                    // 基于服务器给出的目标 FPS 主动丢帧：
                                    // - targetFps <= 0：不过滤，所有帧都尝试编码发送
                                    // - targetFps > 0：按时间间隔丢弃多余帧，平滑控制发送速率
                                    val shouldSend = shouldSendFrame(targetFps)
                                    if (shouldSend) {
                                        val cropRect = computeCropRect(imageProxy)
                                        val frameWidth = cropRect.width()
                                        val frameHeight = cropRect.height()
                                        if (!encoderStarted) {
                                            // 真正以“裁剪后尺寸”初始化编码器，避免被 CameraX 内部 1920x1920 等实际尺寸干扰
                                            encoder.start(frameWidth, frameHeight, encoderBitrate, targetFps)
                                            encoderStarted = true
                                            Log.d(TAG, "H.264 Encoder started with camera resolution ${frameWidth}x${frameHeight}")
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
                val statusMsg = "Streaming H.264 at ${width}x${height} ($fpsLabel)"
                _uiState.update { it.copy(isStreaming = true, statusMessage = statusMsg) }
                sendStatus(ClientStatus("capture_started", statusMsg))

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
            val capabilitiesObj = JSONObject()
                .put("type", "capabilities")
                .put("deviceModel", Build.MODEL ?: "unknown")
                .put("sdkInt", Build.VERSION.SDK_INT)
                .put("resolutions", array)
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

    private fun computeCropRect(imageProxy: ImageProxy): Rect {
        val sensorRect = imageProxy.cropRect ?: Rect(0, 0, imageProxy.width, imageProxy.height)
        var targetWidth = min(sensorRect.width(), requestedWidth)
        var targetHeight = min(sensorRect.height(), requestedHeight)
        if (targetWidth <= 0 || targetHeight <= 0) {
            targetWidth = sensorRect.width()
            targetHeight = sensorRect.height()
        }
        targetWidth = max(2, targetWidth - targetWidth % 2)
        targetHeight = max(2, targetHeight - targetHeight % 2)

        val horizontalPadding = (sensorRect.width() - targetWidth).coerceAtLeast(0) / 2
        val verticalPadding = (sensorRect.height() - targetHeight).coerceAtLeast(0) / 2

        var left = sensorRect.left + horizontalPadding
        var top = sensorRect.top + verticalPadding
        if (left % 2 != 0) left -= 1
        if (top % 2 != 0) top -= 1
        left = left.coerceAtLeast(0)
        top = top.coerceAtLeast(0)

        var right = (left + targetWidth).coerceAtMost(imageProxy.width)
        var bottom = (top + targetHeight).coerceAtMost(imageProxy.height)

        // Ensure even dimensions after clamping
        if ((right - left) % 2 != 0) right -= 1
        if ((bottom - top) % 2 != 0) bottom -= 1

        if (right <= left || bottom <= top) {
            // 若裁剪结果非法，则退回到整帧的“最近偶数”尺寸，保证编码安全
            return Rect(0, 0, imageProxy.width - imageProxy.width % 2, imageProxy.height - imageProxy.height % 2)
        }

        return Rect(left, top, right, bottom)
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
            nv12[uvDstIndex++] = uBuffer.get(uIndex)
            nv12[uvDstIndex++] = vBuffer.get(vIndex)
        }
    }
    return nv12
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
    var showCameraPreview by remember { mutableStateOf(false) }

    if (showCameraPreview) {
        val cameraPermissionState = rememberPermissionState(Manifest.permission.CAMERA)

        BackHandler {
            showCameraPreview = false
        }

        if (cameraPermissionState.status.isGranted) {
            Box(modifier = modifier.fillMaxSize()) {
                CameraPreview(webSocketViewModel)
            }
        } else {
            LaunchedEffect(showCameraPreview) {
                cameraPermissionState.launchPermissionRequest()
            }
            Column(modifier = modifier.padding(16.dp), verticalArrangement = Arrangement.Center) {
                Text("Requesting camera permission...")
                Spacer(modifier = Modifier.size(16.dp))
                Button(onClick = { showCameraPreview = false }) {
                    Text("Back")
                }
            }
        }
    } else {
        MainContent(
            onCameraClick = { showCameraPreview = true },
            modifier = modifier,
            webSocketViewModel = webSocketViewModel
        )
    }
}

@Composable
fun MainContent(
    onCameraClick: () -> Unit,
    modifier: Modifier = Modifier,
    webSocketViewModel: WebSocketViewModel = viewModel()
) {
    val uiState by webSocketViewModel.uiState.collectAsState()

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Button(onClick = onCameraClick) {
            Text(text = "Open Camera")
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
fun CameraPreview(viewModel: WebSocketViewModel = viewModel()) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val context = LocalContext.current
    val imageAnalysis by viewModel.imageAnalysis

    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = {
            PreviewView(it).apply {
                this.scaleType = PreviewView.ScaleType.FILL_CENTER
            }
        },
        update = { previewView ->
            val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
            cameraProviderFuture.addListener({
                val cameraProvider = cameraProviderFuture.get()
                try {
                    cameraProvider.unbindAll()
                    val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA

                    val preview = CameraXPreview.Builder().build().also {
                        it.setSurfaceProvider(previewView.surfaceProvider)
                    }

                    val useCases = mutableListOf<androidx.camera.core.UseCase>(preview)
                    imageAnalysis?.let { useCases.add(it) }

                    cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        cameraSelector,
                        *useCases.toTypedArray()
                    )

                } catch (e: Exception) {
                    Log.e(TAG, "Use case binding failed", e)
                }
            }, ContextCompat.getMainExecutor(context))
        }
    )
}

@ComposablePreview(showBackground = true)
@Composable
fun MainContentPreview() {
    LabLogCameraTheme {
        MainContent(onCameraClick = {})
    }
}
