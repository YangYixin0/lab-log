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
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.media.AudioManager
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.ToneGenerator
import android.media.MediaMuxer
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
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
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import androidx.camera.core.Preview as CameraXPreview
import androidx.compose.ui.tooling.preview.Preview as ComposablePreview

private const val TAG = "LabLogCamera"

// OkHttp WebSocket 发送队列是固定 16MB 的硬限制，超出 send() 会直接返回 false。
// base64 会膨胀约 4/3，为了留出 JSON 和控制帧空间，按 0.5MB 预留。
private const val OKHTTP_WS_MAX_QUEUE_BYTES: Long = 16L * 1024L * 1024L
private const val WS_QUEUE_SAFETY_MARGIN_BYTES: Long = 512L * 1024L
private const val WS_CLIENT_MAX_TEXT_BYTES: Long =
    OKHTTP_WS_MAX_QUEUE_BYTES - WS_QUEUE_SAFETY_MARGIN_BYTES
private const val MAX_MP4_BYTES_PER_SEGMENT: Long =
    ((WS_CLIENT_MAX_TEXT_BYTES) * 3) / 4 // 反推 base64 后不超过队列
private const val MIN_FRAMES_BEFORE_SPLIT = 10

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
    val message: String? = null
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

data class QrDetection(
    val userId: String,
    val content: String,
    val confidence: Float,
    val detectedAtMs: Long
)

data class ClientCapabilities(
    val type: String = "capabilities",
    val deviceModel: String,
    val sdkInt: Int,
    val resolutions: List<ResolutionOption>
)
//endregion

//region MP4分段封装器
/**
 * 使用MediaMuxer封装MP4分段
 * 负责将H264编码数据封装成MP4文件，并在达到分段时长且是关键帧时触发分段完成
 */
class MP4SegmentMuxer(
    private val segmentDurationSeconds: Double,
    private val onSegmentComplete: (ByteArray, String) -> Unit,
    private val onSegmentFinished: (() -> Unit)? = null,  // 分段完成后的回调，用于启动新分段
    private val maxSegmentBytes: Long? = null             // 按大小触发分段（保护 WebSocket 队列）
) {
    private val muxerLock = Any()
    private var mediaMuxer: MediaMuxer? = null
    private var videoTrackIndex: Int = -1
    private var isStarted: Boolean = false
    private var segmentStartTimeUs: Long = 0
    private var segmentSequence: Int = 0
    private var tempFile: java.io.File? = null
    private var firstFrameTimeUs: Long = -1
    private var lastFrameTimeUs: Long = -1
    private var frameCount: Int = 0  // 当前分段的帧数计数
    private var videoWidth: Int = 0
    private var videoHeight: Int = 0
    private var videoFps: Int = 0
    private var cachedSpsBuffer: ByteBuffer? = null  // 缓存的SPS，在分段间复用
    private var cachedPpsBuffer: ByteBuffer? = null  // 缓存的PPS，在分段间复用

    private fun shouldSplitBySize(currentBytes: Long, isKeyframe: Boolean): Boolean {
        val threshold = maxSegmentBytes ?: return false
        return currentBytes >= threshold && isKeyframe && frameCount >= MIN_FRAMES_BEFORE_SPLIT
    }
    
    /**
     * 设置CSD（从MediaCodec的outputFormat中获取）
     * @param sps SPS ByteBuffer
     * @param pps PPS ByteBuffer（可选）
     */
    fun setCSD(sps: ByteBuffer, pps: ByteBuffer?) {
        synchronized(muxerLock) {
            // 复制ByteBuffer内容，避免原始buffer被修改
            val spsArray = ByteArray(sps.remaining())
            sps.duplicate().get(spsArray)
            var finalSps = spsArray
            var finalPps: ByteArray? = null

            if (pps != null) {
                val ppsArray = ByteArray(pps.remaining())
                pps.duplicate().get(ppsArray)
                finalPps = ppsArray
            } else {
                // 某些设备只在 csd-0 中提供 SPS+PPS，尝试拆分
                val (parsedSps, parsedPps) = parseSpsPpsFromBuffer(spsArray)
                parsedSps?.let { spsBuf ->
                    val spsArray = ByteArray(spsBuf.remaining())
                    spsBuf.duplicate().get(spsArray)
                    finalSps = spsArray
                }
                parsedPps?.let { ppsBuf ->
                    val ppsArray = ByteArray(ppsBuf.remaining())
                    ppsBuf.duplicate().get(ppsArray)
                    finalPps = ppsArray
                }
            }

            cachedSpsBuffer = ByteBuffer.wrap(finalSps)
            cachedPpsBuffer = finalPps?.let { ByteBuffer.wrap(it) }
            Log.d(TAG, "MP4SegmentMuxer: CSD set, SPS size=${finalSps.size}, PPS size=${finalPps?.size ?: 0}")
        }
    }
    
    /**
     * 开始新分段
     * @param width 视频宽度
     * @param height 视频高度
     * @param fps 帧率
     */
    fun startSegment(width: Int, height: Int, fps: Int) {
        synchronized(muxerLock) {
            try {
                // 创建临时文件
                tempFile = java.io.File.createTempFile("segment_", ".mp4", null)
                tempFile?.deleteOnExit()
                
                mediaMuxer = MediaMuxer(tempFile!!.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
                videoTrackIndex = -1
                isStarted = false
                segmentStartTimeUs = System.currentTimeMillis() * 1000 // 使用当前时间作为起始时间
                firstFrameTimeUs = -1
                lastFrameTimeUs = -1
                frameCount = 0
                videoWidth = width
                videoHeight = height
                videoFps = fps
                // 不清空缓存的SPS/PPS，在新分段中复用
                
                Log.d(TAG, "MP4SegmentMuxer: Started new segment, temp file: ${tempFile?.absolutePath}, ${width}x${height}@${fps}fps")
            } catch (e: Exception) {
                Log.e(TAG, "MP4SegmentMuxer: Failed to start segment", e)
                throw RuntimeException("Failed to start MP4 segment", e)
            }
        }
    }
    
    /**
     * 添加编码帧到MediaMuxer
     * @param encodedData 编码后的H264数据
     * @param bufferInfo MediaCodec.BufferInfo
     * @return true表示需要开始新分段（达到时长且是关键帧），false表示继续当前分段
     */
    fun addFrame(encodedData: ByteArray, bufferInfo: MediaCodec.BufferInfo): Boolean {
        var shouldFinish = false
        try {
            synchronized(muxerLock) {
                val muxer = mediaMuxer ?: return false
                
                // 检查是否是关键帧
                val isKeyframe = (bufferInfo.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0 ||
                        (encodedData.size > 4 && (encodedData[4].toInt() and 0x1F) == 5)
                
                // 记录第一帧时间
                if (firstFrameTimeUs < 0) {
                    firstFrameTimeUs = bufferInfo.presentationTimeUs
                }
                lastFrameTimeUs = bufferInfo.presentationTimeUs
                
                // 如果还没有添加视频轨道，检查是否有关键帧并提取CSD
                if (videoTrackIndex < 0) {
                    // 仅在关键帧启动新分段
                    if (!isKeyframe) return false

                    // 优先使用缓存的CSD（来自 MediaCodec outputFormat 或上一分段）
                    var spsBuffer = cachedSpsBuffer
                    var ppsBuffer = cachedPpsBuffer

                    // 如果缺少任意一方，尝试从当前关键帧解析并回写缓存
                    if (spsBuffer == null || ppsBuffer == null) {
                        val csd = extractCSDFromKeyframe(encodedData)
                        if (csd != null) {
                            spsBuffer = csd.first
                            ppsBuffer = csd.second
                            cachedSpsBuffer = spsBuffer
                            cachedPpsBuffer = ppsBuffer
                            Log.d(TAG, "MP4SegmentMuxer: Extracted and cached CSD from keyframe (refresh)")
                        } else if (spsBuffer != null && ppsBuffer == null) {
                            // 尝试从已有 SPS 中拆出 PPS（兼容只有 csd-0 的设备）
                            val parsed = parseSpsPpsFromBuffer(spsBuffer.duplicate().let { buf ->
                                val arr = ByteArray(buf.remaining())
                                buf.get(arr)
                                arr
                            })
                            parsed.first?.let { spsBuffer = it }
                            parsed.second?.let { pps ->
                                ppsBuffer = pps
                                cachedPpsBuffer = pps
                                Log.d(TAG, "MP4SegmentMuxer: Recovered PPS from cached SPS buffer")
                            }
                        }
                    }

                    if (spsBuffer != null) {
                        // 创建MediaFormat，包含宽高和CSD
                        val format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, videoWidth, videoHeight).apply {
                            setInteger(MediaFormat.KEY_FRAME_RATE, videoFps)
                            setByteBuffer("csd-0", spsBuffer) // SPS
                            ppsBuffer?.let { setByteBuffer("csd-1", it) } // PPS
                        }
                        videoTrackIndex = muxer.addTrack(format)
                        muxer.start()
                        isStarted = true
                        Log.d(TAG, "MP4SegmentMuxer: Added video track, videoTrackIndex=$videoTrackIndex, ${videoWidth}x${videoHeight}@${videoFps}fps (using cached/parsed CSD)")
                    } else {
                        // 无法提取CSD，等待下一个关键帧
                        Log.w(TAG, "MP4SegmentMuxer: Failed to extract CSD from keyframe, waiting for next keyframe")
                        return false
                    }
                }
                
                // 写入帧数据
                if (isStarted && videoTrackIndex >= 0) {
                    val buffer = ByteBuffer.allocate(bufferInfo.size)
                    buffer.put(encodedData)
                    buffer.position(bufferInfo.offset)
                    buffer.limit(bufferInfo.offset + bufferInfo.size)
                    muxer.writeSampleData(videoTrackIndex, buffer, bufferInfo)
                    frameCount++
                    
                    val currentDurationSeconds = if (firstFrameTimeUs >= 0 && lastFrameTimeUs > firstFrameTimeUs) {
                        (lastFrameTimeUs - firstFrameTimeUs) / 1_000_000.0
                    } else {
                        0.0
                    }
                    val reachedDuration = isKeyframe &&
                            currentDurationSeconds >= 1.0 &&
                            currentDurationSeconds >= segmentDurationSeconds &&
                            frameCount >= MIN_FRAMES_BEFORE_SPLIT
                    val currentFileSize = tempFile?.length() ?: 0L
                    val reachedSize = shouldSplitBySize(currentFileSize, isKeyframe)
                    shouldFinish = reachedDuration || reachedSize
                }
            }
            if (shouldFinish) {
                val finished = finishSegment()
                if (finished) {
                    // 通知需要启动新分段
                    onSegmentFinished?.invoke()
                    return true
                }
            }
            return false
        } catch (e: Exception) {
            Log.e(TAG, "MP4SegmentMuxer: Error adding frame", e)
            throw RuntimeException("Failed to add frame to MP4 segment", e)
        }
    }
    
    /**
     * 完成当前分段，读取MP4数据并回调
     */
    fun finishSegment(): Boolean {
        val result = synchronized(muxerLock) {
            val muxer = mediaMuxer ?: return@synchronized Triple(false, ByteArray(0), "")
            val file = tempFile ?: return@synchronized Triple(false, ByteArray(0), "")
            val hasFrames = isStarted && frameCount > 0
            try {
                if (isStarted) {
                    muxer.stop()
                }
            } catch (e: Exception) {
                Log.e(TAG, "MP4SegmentMuxer: Error stopping muxer", e)
            }
            try {
                muxer.release()
            } catch (e: Exception) {
                Log.e(TAG, "MP4SegmentMuxer: Error releasing muxer", e)
            }
            mediaMuxer = null
            isStarted = false
            videoTrackIndex = -1
            
            val mp4Data = if (hasFrames && file.exists()) file.readBytes() else ByteArray(0)
            file.delete()
            
            val segmentId = generateSegmentIdLocked()
            tempFile = null
            firstFrameTimeUs = -1
            lastFrameTimeUs = -1
            frameCount = 0
            
            Triple(hasFrames && mp4Data.isNotEmpty(), mp4Data, segmentId)
        }

        val (hasData, mp4Data, segmentId) = result
        if (!hasData) {
            Log.w(TAG, "MP4SegmentMuxer: Segment $segmentId is empty, skip sending.")
            return false
        }

        Log.d(TAG, "MP4SegmentMuxer: Segment completed, id=$segmentId, size=${mp4Data.size} bytes")
        onSegmentComplete(mp4Data, segmentId)
        return true
    }

    private fun generateSegmentIdLocked(): String {
        val timestamp = java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.getDefault())
            .format(java.util.Date())
        val segmentId = String.format("%s_%02d", timestamp, segmentSequence)
        segmentSequence = (segmentSequence + 1) % 100 // 两位数，0-99循环
        return segmentId
    }
    
    /**
     * 停止并清理资源
     */
    fun stop() {
        try {
            finishSegment()
        } catch (e: Exception) {
            Log.e(TAG, "MP4SegmentMuxer: Error stopping", e)
        }
        synchronized(muxerLock) {
            try {
                mediaMuxer?.release()
            } catch (_: Exception) {
            }
            mediaMuxer = null
            tempFile?.delete()
            tempFile = null
            isStarted = false
            videoTrackIndex = -1
            frameCount = 0
            firstFrameTimeUs = -1
            lastFrameTimeUs = -1
            segmentSequence = 0
        }
        Log.d(TAG, "MP4SegmentMuxer: Stopped")
    }
    
    /**
     * 从关键帧中提取CSD（SPS/PPS）
     * @return Pair<SPS ByteBuffer, PPS ByteBuffer?>，如果提取失败返回null
     */
    private fun extractCSDFromKeyframe(encodedData: ByteArray): Pair<ByteBuffer, ByteBuffer?>? {
        // 先按 Annex-B 起始码扫描
        var pos = 0
        var sps: ByteArray? = null
        var pps: ByteArray? = null
        
        while (pos < encodedData.size - 4) {
            // 查找起始码
            if (encodedData[pos] == 0x00.toByte() && 
                encodedData[pos + 1] == 0x00.toByte() &&
                encodedData[pos + 2] == 0x00.toByte() &&
                encodedData[pos + 3] == 0x01.toByte()) {
                val nalType = (encodedData[pos + 4].toInt() and 0x1F)
                val startPos = pos + 4
                
                // 查找下一个起始码
                var nextPos = pos + 5
                while (nextPos < encodedData.size - 4) {
                    if (encodedData[nextPos] == 0x00.toByte() &&
                        encodedData[nextPos + 1] == 0x00.toByte() &&
                        encodedData[nextPos + 2] == 0x00.toByte() &&
                        encodedData[nextPos + 3] == 0x01.toByte()) {
                        break
                    }
                    nextPos++
                }
                
                val nalData = if (nextPos < encodedData.size) {
                    encodedData.sliceArray(startPos until nextPos)
                } else {
                    encodedData.sliceArray(startPos until encodedData.size)
                }
                
                when (nalType) {
                    7 -> { // SPS
                        sps = nalData
                    }
                    8 -> { // PPS
                        pps = nalData
                    }
                }
                
                pos = nextPos
            } else if (pos < encodedData.size - 3 &&
                       encodedData[pos] == 0x00.toByte() &&
                       encodedData[pos + 1] == 0x00.toByte() &&
                       encodedData[pos + 2] == 0x01.toByte()) {
                val nalType = (encodedData[pos + 3].toInt() and 0x1F)
                val startPos = pos + 3
                
                var nextPos = pos + 4
                while (nextPos < encodedData.size - 3) {
                    if (encodedData[nextPos] == 0x00.toByte() &&
                        encodedData[nextPos + 1] == 0x00.toByte() &&
                        (encodedData[nextPos + 2] == 0x01.toByte() || 
                         (nextPos + 3 < encodedData.size && encodedData[nextPos + 2] == 0x00.toByte() && encodedData[nextPos + 3] == 0x01.toByte()))) {
                        break
                    }
                    nextPos++
                }
                
                val nalData = if (nextPos < encodedData.size) {
                    encodedData.sliceArray(startPos until nextPos)
                } else {
                    encodedData.sliceArray(startPos until encodedData.size)
                }
                
                when (nalType) {
                    7 -> { // SPS
                        sps = nalData
                    }
                    8 -> { // PPS
                        pps = nalData
                    }
                }
                
                pos = nextPos
            } else {
                pos++
            }
        }
        
        // 如果仍未找到 PPS，尝试处理长度前缀（AVCC）格式
        if (sps == null || pps == null) {
            val parsed = parseSpsPpsFromBuffer(encodedData)
            parsed.first?.let { spsBuf ->
                val spsArray = ByteArray(spsBuf.remaining())
                spsBuf.duplicate().get(spsArray)
                sps = spsArray
            }
            parsed.second?.let { ppsBuf ->
                val ppsArray = ByteArray(ppsBuf.remaining())
                ppsBuf.duplicate().get(ppsArray)
                pps = ppsArray
            }
        }
        
        return if (sps != null) {
            Pair(ByteBuffer.wrap(sps), pps?.let { ByteBuffer.wrap(it) })
        } else {
            null
        }
    }

    /**
     * 尝试从一段字节中解析出 SPS / PPS（兼容 Annex-B 起始码和 AVCC 长度前缀）。
     */
    private fun parseSpsPpsFromBuffer(data: ByteArray): Pair<ByteBuffer?, ByteBuffer?> {
        var sps: ByteArray? = null
        var pps: ByteArray? = null

        fun handleNal(nal: ByteArray) {
            val type = nal.firstOrNull()?.toInt()?.and(0x1F) ?: return
            when (type) {
                7 -> sps = nal
                8 -> pps = nal
            }
        }

        // 优先按起始码扫描
        var i = 0
        while (i <= data.size - 4) {
            val isLongStart = data[i] == 0.toByte() && data[i + 1] == 0.toByte() && data[i + 2] == 0.toByte() && data[i + 3] == 1.toByte()
            val isShortStart = data[i] == 0.toByte() && data[i + 1] == 0.toByte() && data[i + 2] == 1.toByte()
            if (isLongStart || isShortStart) {
                val start = i + if (isLongStart) 4 else 3
                var next = start
                while (next <= data.size - 4) {
                    val nextLong = data[next] == 0.toByte() && data[next + 1] == 0.toByte() && data[next + 2] == 0.toByte() && data[next + 3] == 1.toByte()
                    val nextShort = data[next] == 0.toByte() && data[next + 1] == 0.toByte() && data[next + 2] == 1.toByte()
                    if (nextLong || nextShort) break
                    next++
                }
                val nal = data.sliceArray(start until next.coerceAtMost(data.size))
                handleNal(nal)
                i = next
            } else {
                i++
            }
        }

        // 如果未找到 PPS，再尝试长度前缀 AVCC
        if (pps == null) {
            var offset = 0
            while (offset + 4 <= data.size) {
                val len = ByteBuffer.wrap(data, offset, 4).order(ByteOrder.BIG_ENDIAN).int
                if (len <= 0 || offset + 4 + len > data.size) break
                val nal = data.sliceArray(offset + 4 until offset + 4 + len)
                handleNal(nal)
                offset += 4 + len
                if (sps != null && pps != null) break
            }
        }

        // 仍未找到且看起来是 AVC Decoder Configuration Record，则按 AVCC 规范解析
        if (sps == null || pps == null) {
            val avccParsed = parseSpsPpsFromAvccConfig(data)
            if (avccParsed.first != null && sps == null) {
                sps = avccParsed.first
            }
            if (avccParsed.second != null && pps == null) {
                pps = avccParsed.second
            }
        }

        return Pair(sps?.let { ByteBuffer.wrap(it) }, pps?.let { ByteBuffer.wrap(it) })
    }

    /**
     * 解析 AVC Decoder Configuration Record（avcC box payload）中的 SPS/PPS。
     * 参考 ISO/IEC 14496-15：version(1), profile/compat/level(3), lengthSizeMinusOne(1),
     * numOfSequenceParameterSets(1 & 0x1F), each SPS: 16-bit len + data,
     * numOfPictureParameterSets(1), each PPS: 16-bit len + data。
     */
    private fun parseSpsPpsFromAvccConfig(data: ByteArray): Pair<ByteArray?, ByteArray?> {
        try {
            if (data.size < 7) return Pair(null, null)
            var offset = 0
            val version = data[offset].toInt() and 0xFF
            if (version != 1) return Pair(null, null)
            offset += 4 // version + profile/compat/level
            val lengthSizeMinusOne = data[offset].toInt() and 0x03
            if (lengthSizeMinusOne !in 0..3) return Pair(null, null)
            offset++
            val numSps = data[offset].toInt() and 0x1F
            offset++
            var sps: ByteArray? = null
            repeat(numSps) {
                if (offset + 2 > data.size) return Pair(sps, null)
                val spsLen = ((data[offset].toInt() and 0xFF) shl 8) or (data[offset + 1].toInt() and 0xFF)
                offset += 2
                if (offset + spsLen > data.size) return Pair(sps, null)
                sps = data.copyOfRange(offset, offset + spsLen)
                offset += spsLen
            }
            if (offset >= data.size) return Pair(sps, null)
            val numPps = data[offset].toInt() and 0xFF
            offset++
            var pps: ByteArray? = null
            repeat(numPps) {
                if (offset + 2 > data.size) return Pair(sps, pps)
                val ppsLen = ((data[offset].toInt() and 0xFF) shl 8) or (data[offset + 1].toInt() and 0xFF)
                offset += 2
                if (offset + ppsLen > data.size) return Pair(sps, pps)
                pps = data.copyOfRange(offset, offset + ppsLen)
                offset += ppsLen
            }
            return Pair(sps, pps)
        } catch (_: Exception) {
            return Pair(null, null)
        }
    }
}
//endregion

//region H.264 编码器封装
/**
 * 对 Android 平台的 MediaCodec 进行简单封装：
 * - 通过 start() 进行一次性配置（分辨率 / 码率 / 目标帧率）
 * - encode() 接收 CameraX 的 ImageProxy，完成 YUV->NV12 转换并送入编码器
 * - 编码输出通过回调 onFrameEncoded 向外传递
 */
class H264Encoder(
    private val onFrameEncoded: (EncodedFrame) -> Unit,
    private val mp4Muxer: MP4SegmentMuxer? = null
) {

    private var mediaCodec: MediaCodec? = null
    private var isFirstKeyframeReceived = false  // 是否已收到第一个关键帧
    var encoderWidth: Int = 0
        private set
    var encoderHeight: Int = 0
        private set
    var encoderFps: Int = 0
        private set
    private var encoderColorFormat: Int = MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar

    fun start(width: Int, height: Int, bitrate: Int, targetFps: Int) {
        encoderWidth = width
        encoderHeight = height
        encoderFps = if (targetFps > 0) targetFps else 10
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
            // 确保每个 IDR 前置 SPS/PPS，便于分段解码
            setInteger(MediaFormat.KEY_PREPEND_HEADER_TO_SYNC_FRAMES, 1)
        }
            Log.d(TAG, "Encoder config: ${width}x${height}")

        try {
            mediaCodec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC).apply {
                configure(mediaFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                // 记录实际生效的输入色彩格式（硬件可能忽略请求值）
                encoderColorFormat = this.inputFormat?.getInteger(MediaFormat.KEY_COLOR_FORMAT)
                    ?: MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar
                start()
            }
            Log.d(
                TAG,
                "H.264 Encoder started successfully, colorFormat=$encoderColorFormat"
            )
            
            // 如果使用MP4Muxer，启动第一个分段
            mp4Muxer?.startSegment(width, height, encoderFps)
        } catch (e: IOException) {
            Log.e(TAG, "Failed to create H.264 encoder", e)
        }
    }

    @SuppressLint("UnsafeOptInUsageError")
    fun encode(
        image: ImageProxy,
        cropRect: Rect,
        rotationDegrees: Int = 0,
        timestamp: String? = null,
        charWidth: Int = 12,
        charHeight: Int = 18
    ) {
        val codec = mediaCodec ?: return
        try {
            // 将整帧转换和编码过程都放在 try 中，防止异常向外抛出导致 Analyzer 中断
            val nv12Bytes = image.toNv12ByteArray(cropRect, rotationDegrees, timestamp, charWidth, charHeight)
            val yuvBytes = if (encoderColorFormat == MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Planar) {
                nv12ToI420(nv12Bytes, cropRect.width(), cropRect.height())
            } else {
                nv12Bytes
            }

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
                // 检查输出格式变化（包含CSD数据）
                if (outputBufferIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    val format = codec.outputFormat
                    // 从输出格式中提取CSD（SPS/PPS）
                    val csd0 = format.getByteBuffer("csd-0")  // SPS
                    val csd1 = format.getByteBuffer("csd-1")  // PPS
                    if (csd0 != null) {
                        // 将CSD传递给MP4Muxer缓存
                        mp4Muxer?.setCSD(csd0, csd1)
                        Log.d(TAG, "H264Encoder: Extracted CSD from output format, SPS size=${csd0.remaining()}, PPS size=${csd1?.remaining() ?: 0}")
                    }
                    outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
                    continue
                }
                val outputBuffer = codec.getOutputBuffer(outputBufferIndex)
                if (outputBuffer != null && bufferInfo.size > 0) {
                    val encodedData = ByteArray(bufferInfo.size)
                    outputBuffer.get(encodedData)
                    
                    // 检查是否是关键帧（IDR帧）
                    // 方法1：检查BUFFER_FLAG_KEY_FRAME标志
                    val isKeyframeByFlag = (bufferInfo.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0
                    // 方法2：检查NAL类型（NAL类型5是IDR帧）
                    val isIdrFrame = encodedData.size > 4 && (encodedData[4].toInt() and 0x1F) == 5
                    val isKeyframe = isKeyframeByFlag || isIdrFrame
                    
                    // 如果是第一个关键帧，标记已收到
                    if (!isFirstKeyframeReceived && isKeyframe) {
                        isFirstKeyframeReceived = true
                        Log.d(TAG, "First keyframe received, SPS/PPS should be complete")
                    }
                    
                    // 如果使用MP4Muxer，将帧添加到muxer
                    mp4Muxer?.addFrame(encodedData, bufferInfo)
                    
                    // 使用编码器输出的时间戳作为"设备时间"，与原始图像时间基本一致
                    val timestampMs = bufferInfo.presentationTimeUs / 1000L
                    // 只有在不使用MP4Muxer时才通过回调发送H264帧
                    if (mp4Muxer == null) {
                        onFrameEncoded(EncodedFrame(encodedData, timestampMs))
                    }
                }
                codec.releaseOutputBuffer(outputBufferIndex, false)
                outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
            }
        } catch (e: Exception) {
            if (e is IllegalStateException) {
                Log.w(TAG, "H.264 encoding skipped: codec state error (likely stopped)", e)
            } else {
                Log.e(TAG, "H.264 encoding error", e)
            }
        }
    }

    fun stop() {
        try {
            // 如果使用MP4Muxer，完成最后一个分段
            mp4Muxer?.finishSegment()
            mediaCodec?.let { codec ->
                try {
                    codec.stop()
                } catch (e: IllegalStateException) {
                    Log.w(TAG, "Codec stop skipped (already released)", e)
                }
                try {
                    codec.release()
                } catch (e: IllegalStateException) {
                    Log.w(TAG, "Codec release skipped (already released)", e)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping encoder", e)
        }
        mediaCodec = null
        isFirstKeyframeReceived = false  // 重置状态
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

//region OCR-B 字体渲染器
/**
 * OCR-B 字体渲染器
 * 负责从 TrueType 字体文件加载字体并渲染字符位图
 * 在应用启动时预加载所有时间戳所需的字符
 */
object OcrBFontRenderer {
    private const val TAG = "OcrBFontRenderer"
    private const val FONT_ASSET_PATH = "fonts/OCRB_Regular.ttf"
    
    // 字体对象，可能是 OCR-B 或系统等宽字体
    private var typeface: Typeface? = null
    
    // 字符位图缓存 (字符 -> 位图数组)
    private val charBitmapCache = mutableMapOf<Char, Array<IntArray>>()
    
    // 预加载完成标志
    @Volatile
    private var preloadCompleted = false
    
    // 需要预加载的字符集（时间戳 "YYYY-MM-DDTHH:mm:ss" 所需）
    private const val PRELOAD_CHARS = "0123456789-: Time"
    
    /**
     * 初始化字体渲染器，加载 OCR-B 字体
     * @param context Android Context，用于访问 AssetManager
     */
    fun initialize(context: Context) {
        try {
            // 尝试从 Assets 加载 OCR-B 字体
            typeface = Typeface.createFromAsset(context.assets, FONT_ASSET_PATH)
            Log.d(TAG, "Successfully loaded OCR-B font from $FONT_ASSET_PATH")
        } catch (e: Exception) {
            // 加载失败，回退到系统等宽字体
            Log.e(TAG, "Failed to load OCR-B font, falling back to MONOSPACE", e)
            typeface = Typeface.MONOSPACE
        }
    }
    
    /**
     * 预加载所有时间戳所需的字符位图
     * 应在后台线程调用
     * @param width 字符宽度
     * @param height 字符高度
     */
    fun preloadAllCharacters(width: Int, height: Int) {
        if (typeface == null) {
            Log.e(TAG, "Typeface not initialized, cannot preload characters")
            return
        }
        
        val startTime = System.currentTimeMillis()
        Log.d(TAG, "Starting to preload ${PRELOAD_CHARS.length} characters at ${width}x${height}")
        
        try {
            // 批量渲染所有字符
            PRELOAD_CHARS.forEach { char ->
                val bitmap = renderCharBitmap(char, width, height)
                charBitmapCache[char] = bitmap
            }
            
            preloadCompleted = true
            val duration = System.currentTimeMillis() - startTime
            Log.d(TAG, "Preload completed in ${duration}ms, cached ${charBitmapCache.size} characters")
        } catch (e: Exception) {
            Log.e(TAG, "Error during preload", e)
            preloadCompleted = false
        }
    }
    
    /**
     * 获取缓存的字符位图
     * @param char 要获取的字符
     * @return 字符位图，如果预加载未完成或字符不存在则返回 null
     */
    fun getCachedCharBitmap(char: Char): Array<IntArray>? {
        if (!preloadCompleted) {
            Log.w(TAG, "Preload not completed yet, cannot get char bitmap for '$char'")
            return null
        }
        return charBitmapCache[char]
    }
    
    /**
     * 渲染单个字符的位图
     * @param char 要渲染的字符
     * @param width 目标宽度
     * @param height 目标高度
     * @return 字符位图数组 (行 x 列)，1=白色，0=背景
     */
    private fun renderCharBitmap(char: Char, width: Int, height: Int): Array<IntArray> {
        // 创建临时位图 (ALPHA_8 格式，单通道)
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ALPHA_8)
        val canvas = Canvas(bitmap)
        
        // 配置画笔
        val paint = Paint().apply {
            this.typeface = this@OcrBFontRenderer.typeface
            this.isAntiAlias = true  // 抗锯齿
            this.textAlign = Paint.Align.CENTER
            this.color = android.graphics.Color.WHITE
            
            // 计算合适的字体大小
            // 初始字体大小为高度的 85%
            var testSize = height * 0.85f
            this.textSize = testSize
            
            // 测量字符宽度，如果超出目标宽度则缩小
            val charStr = char.toString()
            var textWidth = measureText(charStr)
            while (textWidth > width && testSize > 1f) {
                testSize -= 0.5f
                this.textSize = testSize
                textWidth = measureText(charStr)
            }
        }
        
        // 计算居中绘制位置
        val x = width / 2f
        val fontMetrics = paint.fontMetrics
        val textHeight = fontMetrics.descent - fontMetrics.ascent
        val y = (height - textHeight) / 2f - fontMetrics.ascent
        
        // 绘制字符
        canvas.drawText(char.toString(), x, y, paint)
        
        // 提取像素数据并转换为二维数组
        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
        
        val result = Array(height) { IntArray(width) }
        for (row in 0 until height) {
            for (col in 0 until width) {
                val pixelIndex = row * width + col
                // Alpha 通道值 > 128 视为白色 (1)，否则为背景 (0)
                val alpha = (pixels[pixelIndex] shr 24) and 0xFF
                result[row][col] = if (alpha > 128) 1 else 0
            }
        }
        
        // 回收临时位图
        bitmap.recycle()
        
        return result
    }
    
    /**
     * 清空缓存（用于内存管理）
     */
    fun clearCache() {
        charBitmapCache.clear()
        preloadCompleted = false
        Log.d(TAG, "Cache cleared")
    }
    
    /**
     * 检查预加载是否完成
     */
    fun isPreloadCompleted(): Boolean = preloadCompleted
}
//endregion

//region 时间戳水印

/**
 * 在 NV12 数据的 Y 平面上绘制时间戳水印
 * @param nv12 NV12 字节数组（Y 平面在前，UV 平面在后）
 * @param width 图像宽度
 * @param height 图像高度
 * @param timestamp 时间戳字符串（格式："Time: hh:mm:ss"）
 * @param charWidth 字符宽度（12 或 16）
 * @param charHeight 字符高度（18 或 24）
 * @param offsetX 左上角 X 偏移（默认 10）
 * @param offsetY 左上角 Y 偏移（默认 10）
 */
fun drawTimestampOnNv12(
    nv12: ByteArray,
    width: Int,
    height: Int,
    timestamp: String,
    charWidth: Int = 16,
    charHeight: Int = 24,
    offsetX: Int = 10,
    offsetY: Int = 10
) {
    // 检查预加载是否完成
    if (!OcrBFontRenderer.isPreloadCompleted()) {
        Log.w(TAG, "OcrBFontRenderer preload not completed, skipping watermark")
        return
    }
    
    // 确保偏移为偶数
    val x = (offsetX / 2) * 2
    val y = (offsetY / 2) * 2
    
    // 计算文本区域大小
    val textWidth = timestamp.length * charWidth
    val textHeight = charHeight
    val padding = 4
    val bgWidth = textWidth + padding * 2
    val bgHeight = textHeight + padding * 2
    
    // 确保背景区域不越界
    if (x + bgWidth > width || y + bgHeight > height) {
        return
    }
    
    // 绘制黑色背景矩形
    val bgY = 0.toByte()  // 黑色
    for (row in y until (y + bgHeight).coerceAtMost(height)) {
        for (col in x until (x + bgWidth).coerceAtMost(width)) {
            val index = row * width + col
            if (index < nv12.size) {
                nv12[index] = bgY
            }
        }
    }
    
    // 绘制白色文字（使用 OCR-B 字体渲染器）
    val textStartX = x + padding
    val textStartY = y + padding
    var charOffsetX = 0
    
    for (char in timestamp) {
        // 从缓存获取字符位图
        val charBitmap = OcrBFontRenderer.getCachedCharBitmap(char)
        if (charBitmap == null) {
            Log.w(TAG, "Character '$char' not found in cache, skipping")
            charOffsetX += charWidth
            continue
        }
        
        // 绘制字符
        for (row in 0 until charHeight) {
            for (col in 0 until charWidth) {
                val dstY = textStartY + row
                val dstX = textStartX + charOffsetX + col
                
                if (dstY < height && dstX < width) {
                    val index = dstY * width + dstX
                    if (index < nv12.size) {
                        if (charBitmap[row][col] == 1) {
                            nv12[index] = 255.toByte()  // 白色
                        }
                    }
                }
            }
        }
        
        charOffsetX += charWidth
    }
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
    
    // 时间戳水印配置
    // 可选值：
    // - TIMESTAMP_MODE_NONE: 无时间戳
    // - TIMESTAMP_MODE_OCRB_16x24: 使用 OCR-B 16×24 字体
    // - TIMESTAMP_MODE_OCRB_20x30: 使用 OCR-B 20×30 字体
    private val TIMESTAMP_MODE_NONE = 0
    private val TIMESTAMP_MODE_OCRB_16x24 = 1
    private val TIMESTAMP_MODE_OCRB_20x30 = 2
    
    // 修改此变量以切换时间戳模式
    private val timestampMode = TIMESTAMP_MODE_OCRB_20x30  // 默认使用 20×30
    
    // 根据模式获取字符尺寸
    private fun getTimestampCharWidth(): Int = when (timestampMode) {
        TIMESTAMP_MODE_OCRB_16x24 -> 16
        TIMESTAMP_MODE_OCRB_20x30 -> 20
        else -> 20  // 默认值
    }
    
    private fun getTimestampCharHeight(): Int = when (timestampMode) {
        TIMESTAMP_MODE_OCRB_16x24 -> 24
        TIMESTAMP_MODE_OCRB_20x30 -> 30
        else -> 30  // 默认值
    }
    
    // 时间戳缓存（每秒更新一次）
    @Volatile
    private var cachedTimestamp: String = ""
    @Volatile
    private var cachedTimestampSecond: Long = -1
    private val qrScanner by lazy {
        BarcodeScanning.getClient(
            BarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build()
        )
    }
    private val qrExecutor = Executors.newSingleThreadExecutor()
    private val qrCache = ConcurrentHashMap<String, QrDetection>()
    private val qrScanInFlight = AtomicBoolean(false)
    private var lastQrSampleMs: Long = 0L
    private val qrToneGenerator = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 80)
    private var lastToneUser: String? = null
    private var lowLightHits: Int = 0
    private var lastHintAtMs: Long = 0L
    
    init {
        // 初始化 OCR-B 字体渲染器
        OcrBFontRenderer.initialize(application)
        
        // 在后台线程预加载字符位图
        if (timestampMode != TIMESTAMP_MODE_NONE) {
            viewModelScope.launch(Dispatchers.IO) {
                val width = getTimestampCharWidth()
                val height = getTimestampCharHeight()
                OcrBFontRenderer.preloadAllCharacters(width, height)
            }
        }
    }
    
    /**
     * 获取当前时间戳字符串，格式为 ISO 8601 "YYYY-MM-DDTHH:mm:ss"（24小时格式）
     * 每秒更新一次缓存，减少字符串格式化开销
     */
    fun getCurrentTimestampString(): String {
        val currentTime = System.currentTimeMillis()
        val currentSecond = currentTime / 1000
        
        if (currentSecond != cachedTimestampSecond) {
            val calendar = java.util.Calendar.getInstance()
            calendar.timeInMillis = currentTime
            val year = calendar.get(java.util.Calendar.YEAR)
            val month = calendar.get(java.util.Calendar.MONTH) + 1  // Calendar.MONTH is 0-based
            val day = calendar.get(java.util.Calendar.DAY_OF_MONTH)
            val hour = calendar.get(java.util.Calendar.HOUR_OF_DAY)
            val minute = calendar.get(java.util.Calendar.MINUTE)
            val second = calendar.get(java.util.Calendar.SECOND)
            cachedTimestamp = String.format("%04d-%02d-%02d Time %02d:%02d:%02d", year, month, day, hour, minute, second)
            cachedTimestampSecond = currentSecond
        }
        
        return cachedTimestamp
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

    @OptIn(ExperimentalCamera2Interop::class)
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

    /**
     * 将 ImageAnalysis 目标分辨率限制在不高于 1280x720，同时保持原始宽高比。
     */
    private fun clampResolution(size: AndroidSize, maxWidth: Int = 1280, maxHeight: Int = 720): AndroidSize {
        val width = size.width.toDouble()
        val height = size.height.toDouble()
        val scale = min(1.0, min(maxWidth / width, maxHeight / height))
        val newWidth = (width * scale).toInt().coerceAtLeast(1)
        val newHeight = (height * scale).toInt().coerceAtLeast(1)
        // 确保为偶数，便于后续 NV12 对齐
        val evenWidth = if (newWidth % 2 == 0) newWidth else newWidth - 1
        val evenHeight = if (newHeight % 2 == 0) newHeight else newHeight - 1
        return AndroidSize(evenWidth, evenHeight)
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
                val cappedResolution = clampResolution(maxResolution)

                val tempAnalysis = ImageAnalysis.Builder()
                    .setTargetResolution(cappedResolution)
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

                        // fps 缺省或为 0 时表示"不限制帧率"，Analyzer 尽可能多发
                        val fps = payload.optInt("fps", 0)
                        // segmentDuration 缺省为 60.0 秒
                        val segmentDuration = payload.optDouble("segmentDuration", 60.0)
                        startStreaming(aspectRatio, bitrateBps, fps, segmentDuration)
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

    private fun startStreaming(aspectRatio: Rational, bitrate: Int, fps: Int, segmentDuration: Double = 60.0) {
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
                resetQrState()

                // 创建MP4SegmentMuxer（使用var以便在回调中引用）
                var mp4Muxer: MP4SegmentMuxer? = null
                mp4Muxer = MP4SegmentMuxer(
                    segmentDuration,
                    onSegmentComplete = { mp4Data, segmentId ->
                        // 分段完成回调：发送MP4分段到服务器
                        sendMP4Segment(mp4Data, segmentId)
                    },
                    onSegmentFinished = {
                        // 分段完成后，启动新分段（在后台线程）
                        viewModelScope.launch(Dispatchers.IO) {
                            try {
                                val encoder = h264Encoder
                                if (encoder != null) {
                                    mp4Muxer?.startSegment(encoder.encoderWidth, encoder.encoderHeight, encoder.encoderFps)
                                }
                            } catch (e: Exception) {
                                Log.e(TAG, "Failed to start new segment", e)
                            }
                        }
                    },
                    maxSegmentBytes = MAX_MP4_BYTES_PER_SEGMENT
                )
                
                // 创建H264Encoder，传入MP4Muxer
                h264Encoder = H264Encoder(
                    onFrameEncoded = { encodedFrame ->
                        // 不再发送H264帧，MP4分段由MP4Muxer回调发送
                    },
                    mp4Muxer = mp4Muxer
                )

                // 获取显示旋转，确保 ImageAnalysis 和 Preview 使用相同的旋转
                // 保持 Preview/ImageAnalysis 按显示旋转方向对齐，避免预览误转
                val windowManager = getApplication<Application>().getSystemService(Context.WINDOW_SERVICE) as? WindowManager
                val displayRotation = windowManager?.defaultDisplay?.rotation ?: Surface.ROTATION_0
                val targetRotation = displayRotation

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
                val targetAnalysisResolution = AndroidSize(
                    requestedWidth.coerceAtLeast(2),
                    requestedHeight.coerceAtLeast(2)
                )
                Log.d(
                    TAG,
                    "ImageAnalysis targetResolution (requested), facing=$currentFacing: ${targetAnalysisResolution.width}x${targetAnalysisResolution.height}, raw max=${maxResolution.width}x${maxResolution.height}, requestedAspectRatio=${aspectRatio.numerator}:${aspectRatio.denominator}"
                )

                val analysisBuilder = ImageAnalysis.Builder()
                    .setTargetResolution(targetAnalysisResolution) // 与编码目标保持一致的宽高比和分辨率
                    .setTargetRotation(targetRotation) // 与 Preview 同步，让 HAL 统一旋转
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
                                    // 使用物理方向 + 摄像头映射得到需要的编码旋转，避免依赖 targetRotation 造成误差
                                    val rotationDegrees = calculateRotationForBackend(_devicePhysicalRotation.value, currentFacing)
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
                                        val currentFacing = _selectedCameraFacing.value
                                        // 计算需要旋转的角度（用于 Android 端旋转）
                                    // 使用 CameraX 提供的旋转角度对 NV12 进行旋转，保持画面方向正确
                                        val rotationDegreesForAndroid = rotationDegrees

                                        // 计算旋转后的图像尺寸
                                        val (rotatedWidth, rotatedHeight) = getRotatedDimensions(
                                            imageProxy.width,
                                            imageProxy.height,
                                            rotationDegreesForAndroid
                                        )

                                        // 创建一个临时的 ImageProxy 包装器，用于计算裁剪区域
                                        // 实际上我们需要基于旋转后的尺寸计算裁剪区域
                                        // 由于 computeSafeAlignedRect 需要 ImageProxy，我们需要传递原始 imageProxy
                                        // 但裁剪区域应该基于旋转后的尺寸
                                        // 解决方案：先计算裁剪区域（基于原始尺寸），然后在 toNv12ByteArray 中处理旋转
                                        // 但这样 cropRect 就不对了
                                        // 更好的方案：修改 computeSafeAlignedRect 接受宽度和高度参数
                                        // 或者创建一个包装类

                                        // 临时方案：如果旋转了90/270度，交换宽高来计算裁剪区域
                                        val cropRect = lockedCropRect ?: computeAlignedCropRectForRotatedFrame(
                                            rotatedWidth,
                                            rotatedHeight,
                                            desiredAspect
                                        ).also {
                                            lockedCropRect = it
                                            Log.d(TAG, "Locked crop rect: ${it.width()}x${it.height()}, rotation=$rotationDegreesForAndroid, rotatedSize=${rotatedWidth}x${rotatedHeight}")
                                        }

                                        val frameWidth = cropRect.width()
                                        val frameHeight = cropRect.height()
                                        if (!encoderStarted) {
                                            // 以"旋转+裁剪后尺寸"初始化编码器
                                            encoder.start(frameWidth, frameHeight, encoderBitrate, targetFps)
                                            encoderStarted = true
                                            Log.d(TAG, "H.264 Encoder started: ${frameWidth}x${frameHeight}, physicalRotation=$physicalRotation, cameraFacing=$currentFacing, rotationForAndroid=$rotationDegreesForAndroid")
                                        }

                                        // 调用 encode，根据配置决定是否传入时间戳
                                        if (timestampMode != TIMESTAMP_MODE_NONE) {
                                            val timestamp = getCurrentTimestampString()
                                            encoder.encode(
                                                imageProxy,
                                                cropRect,
                                                rotationDegreesForAndroid,
                                                timestamp,
                                                getTimestampCharWidth(),
                                                getTimestampCharHeight()
                                            )
                                        } else {
                                            // 无时间戳模式
                                            encoder.encode(
                                                imageProxy,
                                                cropRect,
                                                rotationDegreesForAndroid
                                            )
                                        }
                                    } else if (targetFps > 0) {
                                        droppedFrames++
                                        if (droppedFrames <= 5 || droppedFrames % targetFps == 0) {
                                            Log.v(TAG, "Frame dropped to honor ${targetFps}fps target (dropped=$droppedFrames)")
                                        }
                                    }
                                }
                                // 独立的二维码采样，不影响编码分辨率
                                maybeScanQr(imageProxy)
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
                val statusMsg = "Streaming H.264 at ${aspectRatio.numerator}:${aspectRatio.denominator} aspect ratio, ${bitrateMb}MB bitrate ($fpsLabel) [rotated on Android]"
                _uiState.update { it.copy(isStreaming = true, statusMessage = statusMsg) }
                // 发送 capture_started 状态（视频已在 Android 端旋转完成，无需发送 rotation）
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
            lockedCropRect = null  // 清除锁定的裁剪区域
            lastCropOrientationPortrait = null
            requestedAspectRatio = null
            requestedFps = 0
            lastFrameSentTimeNs = 0L
            droppedFrames = 0
            resetQrState()

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
                val sent = webSocket?.send(statusJson) ?: false
                if (sent) {
                    Log.d(TAG, "--> Sent status: $statusJson")
                } else {
                    Log.e(TAG, "Failed to send status (send returned false): $statusJson")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to send status", e)
            }
        }
    }
    
    /**
     * 发送MP4分段到服务器
     * @param mp4Data MP4文件数据
     * @param segmentId 分段ID（格式：时间戳_序号）
     */
    private fun sendMP4Segment(mp4Data: ByteArray, segmentId: String) {
        if (!_uiState.value.isConnected) {
            Log.w(TAG, "Not connected, cannot send MP4 segment")
            // 连接已断，直接停止推流，避免继续编码
            stopStreaming()
            return
        }
        if (mp4Data.isEmpty()) {
            Log.w(TAG, "MP4 segment is empty, skip send: $segmentId")
            return
        }
        
        viewModelScope.launch(Dispatchers.IO) {
            try {
                // Base64编码MP4数据
                val base64Data = android.util.Base64.encodeToString(mp4Data, android.util.Base64.NO_WRAP)
                val base64Bytes = base64Data.length.toLong() // base64 仅包含 ASCII
                val base64SizeMb = base64Bytes / (1024.0 * 1024.0)
                if (base64Bytes > WS_CLIENT_MAX_TEXT_BYTES) {
                    val limitMb = WS_CLIENT_MAX_TEXT_BYTES / (1024.0 * 1024.0)
                    Log.e(TAG, "MP4 segment too large for WebSocket queue (${String.format("%.2f", base64SizeMb)} MB > ${String.format("%.2f", limitMb)} MB), stopping stream.")
                    sendStatus(ClientStatus("error", "MP4 segment too large for WebSocket queue, please lower bitrate or segment duration"))
                    stopStreaming()
                    return@launch
                }

                val qrArray = JSONArray()
                // 使用快照避免与扫描线程并发冲突
                val qrSnapshot = qrCache.values.toList()
                val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSSXXX", Locale.getDefault())
                qrSnapshot.forEach { qr ->
                    val detectedIso = try {
                        sdf.format(Date(qr.detectedAtMs))
                    } catch (_: Exception) {
                        qr.detectedAtMs.toString()
                    }
                    val obj = JSONObject()
                        .put("confidence", qr.confidence)
                        .put("detected_at_ms", qr.detectedAtMs)
                        .put("detected_at", detectedIso)
                    try {
                        val parsed = JSONObject(qr.content)
                        parsed.optString("user_id").takeIf { it.isNotBlank() }?.let { obj.put("user_id", it) }
                        parsed.optString("public_key_fingerprint").takeIf { it.isNotBlank() }?.let { obj.put("public_key_fingerprint", it) }
                    } catch (_: Exception) {
                        // 非 JSON 内容，忽略解析错误
                    }
                    qrArray.put(obj)
                }
                
                // 构造JSON消息
                val message = JSONObject().apply {
                    put("type", "mp4_segment")
                    put("segment_id", segmentId)
                    put("data", base64Data)
                    put("size", mp4Data.size)
                    put("qr_results", qrArray)
                }.toString()
                
                val sent = webSocket?.send(message) ?: false
                if (sent) {
                    Log.d(TAG, "--> Sent MP4 segment: $segmentId, size=${mp4Data.size} bytes")
                    // 发送后清空当前分段缓存，准备下一分段聚合
                    resetQrState()
                } else {
                    Log.e(TAG, "Failed to send MP4 segment (webSocket send returned false): $segmentId")
                    sendStatus(ClientStatus("error", "Failed to send MP4 segment: send returned false"))
                    // 主动关闭并清空连接，避免后续继续使用坏连接
                    try {
                        webSocket?.cancel()
                    } catch (_: Exception) {
                    }
                    webSocket = null
                    _uiState.update { it.copy(isConnected = false) }
                    stopStreaming()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to send MP4 segment: $segmentId", e)
                // 发送错误状态
                sendStatus(ClientStatus("error", "Failed to send MP4 segment: ${e.message}"))
                try {
                    webSocket?.cancel()
                } catch (_: Exception) {
                }
                webSocket = null
                _uiState.update { it.copy(isConnected = false) }
                stopStreaming()
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
        qrExecutor.shutdown()
        try {
            qrToneGenerator.release()
        } catch (e: Exception) {
            Log.w(TAG, "Failed to release ToneGenerator", e)
        }
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

    private fun shouldSampleQr(nowMs: Long, intervalMs: Long = 300L): Boolean {
        if (qrScanInFlight.get()) return false
        if (nowMs - lastQrSampleMs < intervalMs) return false
        lastQrSampleMs = nowMs
        return true
    }

    private fun playToneForUser(userId: String, isHigherConfidence: Boolean) {
        if (lastToneUser != userId || isHigherConfidence) {
            // 切换到主线程播放提示音，确保音频系统正常工作
            viewModelScope.launch(Dispatchers.Main) {
                try {
                    qrToneGenerator.startTone(ToneGenerator.TONE_PROP_ACK, 150)
                    Log.d(TAG, "QR: Played tone for user: $userId")
                } catch (e: Exception) {
                    Log.w(TAG, "QR: Failed to play tone", e)
                }
            }
            lastToneUser = userId
        }
    }

    private fun showQrHint(hint: String, ttlMs: Long = 1500L, minIntervalMs: Long = 500L) {
        val now = SystemClock.elapsedRealtime()
        if (now - lastHintAtMs < minIntervalMs && _uiState.value.qrHint == hint) {
            return
        }
        lastHintAtMs = now
        _uiState.update { it.copy(qrHint = hint) }
        viewModelScope.launch(Dispatchers.Main) {
            delay(ttlMs)
            _uiState.update { state ->
                if (state.qrHint == hint) state.copy(qrHint = null) else state
            }
        }
    }

    private fun computeQrConfidence(barcode: Barcode): Float {
        val box = barcode.boundingBox ?: return 0.0f
        val area = box.width().toFloat() * box.height().toFloat()
        return area.coerceAtLeast(0f)
    }

    private fun maybeScanQr(imageProxy: ImageProxy) {
        val now = SystemClock.elapsedRealtime()
        if (!shouldSampleQr(now)) return
        qrScanInFlight.set(true)

        // 将当前帧复制为 NV21，避免阻塞 CameraX 管线
        val nv21 = try {
            imageProxy.toNv21ByteArray()
        } catch (e: Exception) {
            Log.w(TAG, "QR: failed to copy NV21", e)
            qrScanInFlight.set(false)
            return
        }
        val width = imageProxy.width
        val height = imageProxy.height
        val rotation = imageProxy.imageInfo.rotationDegrees

        qrExecutor.execute {
            val input = InputImage.fromByteArray(
                nv21,
                width,
                height,
                rotation,
                InputImage.IMAGE_FORMAT_NV21
            )
            qrScanner
                .process(input)
                .addOnSuccessListener { barcodes ->
                    if (barcodes.isEmpty()) {
                        lowLightHits++
                        if (lowLightHits >= 3) {
                            showQrHint("请补光/保持稳定")
                            lowLightHits = 0
                        }
                        return@addOnSuccessListener
                    }
                    lowLightHits = 0
                    barcodes.forEach { code ->
                        val content = code.rawValue ?: return@forEach
                        val dedupKey = try {
                            val obj = JSONObject(content)
                            val uid = obj.optString("user_id", "")
                            val fp = obj.optString("public_key_fingerprint", "")
                            if (uid.isNotBlank() || fp.isNotBlank()) {
                                "uid=$uid|fp=$fp"
                            } else {
                                content
                            }
                        } catch (_: Exception) {
                            content
                        }
                        val confidence = computeQrConfidence(code)
                        val detectedAt = System.currentTimeMillis()
                        qrCache.compute(dedupKey) { _, prev ->
                            val shouldReplace = prev == null || confidence > prev.confidence
                            if (shouldReplace) {
                                playToneForUser(dedupKey, prev != null)
                                showQrHint("已识别用户")
                                QrDetection(
                                    userId = dedupKey,
                                    content = content,
                                    confidence = confidence,
                                    detectedAtMs = detectedAt
                                )
                            } else {
                                prev
                            }
                        }
                    }
                }
                .addOnFailureListener { e ->
                    Log.w(TAG, "QR scan failed", e)
                }
                .addOnCompleteListener {
                    qrScanInFlight.set(false)
                }
        }
    }

    private fun resetQrState() {
        qrCache.clear()
        lastToneUser = null
        lowLightHits = 0
        qrScanInFlight.set(false)
        _uiState.update { it.copy(qrHint = null) }
    }

    private fun formatFpsLabel(fpsValue: Int): String {
        return if (fpsValue <= 0) "unlimited fps" else "${fpsValue}fps"
    }

    /**
     * 编码器对齐裁剪：按目标宽高比居中裁剪，基准宽 1920，32/偶数对齐。
     * 无论设备横竖，都使用同一横向比例，方向由 rotationForBackend 处理。
     * 1:1 时使用全帧（不裁剪），但做 32 对齐以避免条纹。
     */
    /**
     * 安全尺寸裁剪：根据选择的宽高比选择接近的安全尺寸，始终裁剪宽>高的区域。
     * 1:1 时使用全帧（不裁剪），但做 32 对齐以避免条纹。
     *
     * @param imageProxy 图像代理（可能是旋转后的图像）
     * @param desiredAspect 目标宽高比
     */
    private fun computeSafeAlignedRect(imageProxy: ImageProxy, desiredAspect: Rational): Rect {
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

        // 始终裁剪宽>高的区域：
        // - 16:9 时，裁剪 1920x1088（32/偶数对齐）
        // - 其它（含 4:3）时，裁剪 1920x1472
        val is16by9 = isAspectApprox(desiredAspect, 16, 9)
        val targetW = if (is16by9) minOf(1920, imageWidth) else minOf(1920, imageWidth)
        val targetH = if (is16by9) minOf(1088, imageHeight) else minOf(1472, imageHeight)

        // 确保宽>高
        val finalW = maxOf(targetW, targetH).coerceAtMost(imageWidth)
        val finalH = minOf(targetW, targetH).coerceAtMost(imageHeight)

        // 32/偶数对齐
        var cropW = (finalW / 32) * 32
        var cropH = (finalH / 32) * 32
        if (cropW < 2) cropW = 2
        if (cropH < 2) cropH = 2
        if (cropW % 2 != 0) cropW -= 1
        if (cropH % 2 != 0) cropH -= 1

        // 确保宽>高
        if (cropW <= cropH) {
            // 如果宽<=高，交换宽高
            val temp = cropW
            cropW = cropH
            cropH = temp
            // 重新对齐
            cropW = ((cropW / 32) * 32).let { if (it % 2 != 0) it - 1 else it }.coerceAtLeast(2)
            cropH = ((cropH / 32) * 32).let { if (it % 2 != 0) it - 1 else it }.coerceAtLeast(2)
        }

        val left = ((imageWidth - cropW) / 2).coerceAtLeast(0)
        val top = ((imageHeight - cropH) / 2).coerceAtLeast(0)
        val right = (left + cropW).coerceAtMost(imageWidth)
        val bottom = (top + cropH).coerceAtMost(imageHeight)
        return Rect(left, top, right, bottom)
    }

    /**
     * 基于旋转后的尺寸计算裁剪区域，保持目标宽高比并做 32/偶数对齐。
     * - 输入为“旋转后的”宽高（rotationDegreesForAndroid 已经决定了最终方向）
     * - 优先使用可用的最大宽度/高度，按比例回退，避免被强制成 1:1
     */
    private fun computeAlignedCropRectForRotatedFrame(
        rotatedWidth: Int,
        rotatedHeight: Int,
        desiredAspect: Rational
    ): Rect {
        val safeNum = desiredAspect.numerator.coerceAtLeast(1)
        val safeDen = desiredAspect.denominator.coerceAtLeast(1)
        val aspect = safeNum.toDouble() / safeDen.toDouble()

        val maxW = (rotatedWidth / 2) * 2
        val maxH = (rotatedHeight / 2) * 2

        fun alignEven32(value: Int): Int {
            var res = (value / 32) * 32
            if (res < 2) res = 2
            if (res % 2 != 0) res -= 1
            return res
        }

        // 先按比例取最大可用尺寸，再做 32/偶数对齐
        var cropW = maxW
        var cropH = (cropW / aspect).toInt()
        if (cropH > maxH) {
            cropH = maxH
            cropW = (cropH * aspect).toInt()
        }

        cropW = alignEven32(cropW)
        cropH = alignEven32(cropH)

        // 对齐后如仍越界，回退到可用最大值
        if (cropW > maxW) cropW = alignEven32(maxW)
        if (cropH > maxH) cropH = alignEven32(maxH)

        // 目标为横屏比例时，确保宽 > 高；如不满足，再次按比例回退
        if (aspect > 1.0 && cropW <= cropH) {
            cropW = alignEven32(maxW)
            cropH = alignEven32((cropW / aspect).toInt())
            if (cropH > maxH) {
                cropH = alignEven32(maxH)
                cropW = alignEven32((cropH * aspect).toInt())
            }
        }

        val left = ((rotatedWidth - cropW) / 2).coerceAtLeast(0)
        val top = ((rotatedHeight - cropH) / 2).coerceAtLeast(0)
        val right = (left + cropW).coerceAtMost(rotatedWidth)
        val bottom = (top + cropH).coerceAtMost(rotatedHeight)
        return Rect(left, top, right, bottom)
    }

    private fun isAspectApprox(r: Rational, num: Int, den: Int, tol: Float = 0.03f): Boolean {
        val ratio = r.numerator.toFloat() / r.denominator.coerceAtLeast(1)
        val target = num.toFloat() / den.coerceAtLeast(1)
        return kotlin.math.abs(ratio - target) <= tol
    }

    /**
     * 计算旋转后的图像尺寸
     * @param width 原始宽度
     * @param height 原始高度
     * @param rotationDegrees 旋转角度（0, 90, 180, 270）
     * @return Pair<宽度, 高度>
     */
    private fun getRotatedDimensions(width: Int, height: Int, rotationDegrees: Int): Pair<Int, Int> {
        return when (rotationDegrees) {
            90, 270 -> Pair(height, width)  // 宽高互换
            0, 180 -> Pair(width, height)   // 尺寸不变
            else -> Pair(width, height)
        }
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
 * 将 ImageProxy 转换为 NV21（Y + 交错 VU），供 ML Kit 使用。
 * 不做裁剪或缩放，尽量减少额外开销。
 */
@SuppressLint("UnsafeOptInUsageError")
fun ImageProxy.toNv21ByteArray(): ByteArray {
    val yPlane = planes[0].buffer.duplicate()
    val uPlane = planes[1].buffer.duplicate()
    val vPlane = planes[2].buffer.duplicate()

    val ySize = yPlane.remaining()
    val nv21 = ByteArray(ySize + width * height / 2)
    yPlane.get(nv21, 0, ySize)

    val chromaHeight = height / 2
    val chromaWidth = width / 2
    val uRowStride = planes[1].rowStride
    val vRowStride = planes[2].rowStride
    val uPixelStride = planes[1].pixelStride
    val vPixelStride = planes[2].pixelStride

    var outputOffset = ySize
    for (row in 0 until chromaHeight) {
        var uIndex = row * uRowStride
        var vIndex = row * vRowStride
        for (col in 0 until chromaWidth) {
            nv21[outputOffset++] = vPlane.get(vIndex)
            nv21[outputOffset++] = uPlane.get(uIndex)
            uIndex += uPixelStride
            vIndex += vPixelStride
        }
    }
    return nv21
}

/**
 * 将 NV12 转为 I420（Y + U + V 平面），用于只支持 YUV420Planar 的编码器。
 */
fun nv12ToI420(nv12: ByteArray, width: Int, height: Int): ByteArray {
    val ySize = width * height
    val uvSize = ySize / 4
    val i420 = ByteArray(ySize + uvSize * 2)
    // Y 平面
    System.arraycopy(nv12, 0, i420, 0, ySize)
    // NV12 的 UV 交错：UV UV ...
    var src = ySize
    var uDst = ySize
    var vDst = ySize + uvSize
    while (src + 1 < nv12.size && vDst < i420.size) {
        val u = nv12[src].toInt()
        val v = nv12[src + 1].toInt()
        i420[uDst++] = u.toByte()
        i420[vDst++] = v.toByte()
        src += 2
    }
    return i420
}

/**
 * 将 CameraX 的 YUV_420_888 三平面数据转换为 NV12（YUV420 半平面：Y + 交错 UV）。
 * 布局与 COLOR_FormatYUV420SemiPlanar 对应，可显著减少绿色/紫色色块等伪影。
 *
 * 注意：
 * - 如果 rotationDegrees != 0，先旋转整个图像，然后从旋转后的图像中裁剪 cropRect 区域
 * - cropRect 是基于旋转后图像尺寸的裁剪区域
 * - 所有坐标 / 宽高都强制为偶数，以满足很多硬件编码器对 UV 对齐的要求。
 *
 * @param cropRect 裁剪区域（基于旋转后的图像尺寸）
 * @param rotationDegrees 旋转角度（0, 90, 180, 270）
 * @param timestamp 时间戳字符串（可选，格式："Time: hh:mm:ss"），如果为 null 则不绘制
 * @param charWidth 字符宽度（12 或 16）
 * @param charHeight 字符高度（18 或 24）
 */
@SuppressLint("UnsafeOptInUsageError")
fun ImageProxy.toNv12ByteArray(
    cropRect: Rect,
    rotationDegrees: Int = 0,
    timestamp: String? = null,
    charWidth: Int = 12,
    charHeight: Int = 18
): ByteArray {
    val imageWidth = width
    val imageHeight = height

    // 如果不需要旋转，使用原有逻辑
    if (rotationDegrees == 0) {
        val safeRect = cropRect.ensureEvenBounds(imageWidth, imageHeight)
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
        
        // 绘制时间戳（如果提供）
        if (timestamp != null) {
            drawTimestampOnNv12(nv12, cropWidth, cropHeight, timestamp, charWidth, charHeight)
        }
        
        return nv12
    }

    // 需要旋转：先旋转整个图像，然后裁剪
    // 计算旋转后的图像尺寸
    val (rotatedWidth, rotatedHeight) = when (rotationDegrees) {
        90, 270 -> Pair(imageHeight, imageWidth)  // 宽高互换
        0, 180 -> Pair(imageWidth, imageHeight)    // 尺寸不变
        else -> Pair(imageWidth, imageHeight)
    }

    // 确保裁剪区域在旋转后的图像范围内
    val safeRect = cropRect.ensureEvenBounds(rotatedWidth, rotatedHeight)
    val cropWidth = safeRect.width()
    val cropHeight = safeRect.height()
    
    // 对齐到32且为偶数
    val alignedCropWidth = ((cropWidth / 32) * 32).let { if (it % 2 != 0) it - 1 else it }.coerceAtLeast(2)
    val alignedCropHeight = ((cropHeight / 32) * 32).let { if (it % 2 != 0) it - 1 else it }.coerceAtLeast(2)
    
    // 基于原始裁剪区域的中心点，计算对齐后的裁剪位置
    // 这样可以保留原始裁剪意图，同时确保对齐后的尺寸匹配
    val originalCenterX = safeRect.left + cropWidth / 2
    val originalCenterY = safeRect.top + cropHeight / 2
    val cropLeft = (originalCenterX - alignedCropWidth / 2).coerceIn(0, rotatedWidth - alignedCropWidth)
    val cropTop = (originalCenterY - alignedCropHeight / 2).coerceIn(0, rotatedHeight - alignedCropHeight)
    
    val ySize = alignedCropWidth * alignedCropHeight
    val uvSize = ySize / 2
    val nv12 = ByteArray(ySize + uvSize)
    
    // 获取源图像数据
    val yPlane = planes[0]
    val uPlane = planes[1]
    val vPlane = planes[2]
    val yBuffer = yPlane.buffer.duplicate()
    val uBuffer = uPlane.buffer.duplicate()
    val vBuffer = vPlane.buffer.duplicate()
    val yRowStride = yPlane.rowStride
    val uRowStride = uPlane.rowStride
    val vRowStride = vPlane.rowStride
    val uPixelStride = uPlane.pixelStride
    val vPixelStride = vPlane.pixelStride
    
    // 创建临时缓冲区存储旋转后的完整图像
    val rotatedYSize = rotatedWidth * rotatedHeight
    val rotatedY = ByteArray(rotatedYSize)
    val rotatedUVSize = rotatedYSize / 2
    val rotatedUV = ByteArray(rotatedUVSize)
    
    // 旋转 Y 平面
    for (y in 0 until imageHeight) {
        for (x in 0 until imageWidth) {
            val srcIndex = y * yRowStride + x
            val srcY = yBuffer.get(srcIndex)
            
            val (dstX, dstY) = when (rotationDegrees) {
                90 -> Pair(imageHeight - 1 - y, x)           // 顺时针90度
                180 -> Pair(imageWidth - 1 - x, imageHeight - 1 - y)  // 180度
                270 -> Pair(y, imageWidth - 1 - x)           // 逆时针90度（顺时针270度）
                else -> Pair(x, y)
            }
            
            if (dstX in 0 until rotatedWidth && dstY in 0 until rotatedHeight) {
                val dstIndex = dstY * rotatedWidth + dstX
                rotatedY[dstIndex] = srcY
            }
        }
    }
    
    // 旋转 UV 平面（按2x2块）
    val chromaWidth = imageWidth / 2
    val chromaHeight = imageHeight / 2
    val rotatedChromaWidth = rotatedWidth / 2
    val rotatedChromaHeight = rotatedHeight / 2
    
    for (cy in 0 until chromaHeight) {
        for (cx in 0 until chromaWidth) {
            val uIndex = cy * uRowStride + cx * uPixelStride
            val vIndex = cy * vRowStride + cx * vPixelStride
            val u = uBuffer.get(uIndex)
            val v = vBuffer.get(vIndex)
            
            val (dstCX, dstCY) = when (rotationDegrees) {
                90 -> Pair(chromaHeight - 1 - cy, cx)
                180 -> Pair(chromaWidth - 1 - cx, chromaHeight - 1 - cy)
                270 -> Pair(cy, chromaWidth - 1 - cx)
                else -> Pair(cx, cy)
            }
            
            if (dstCX in 0 until rotatedChromaWidth && dstCY in 0 until rotatedChromaHeight) {
                val dstUVIndex = dstCY * rotatedChromaWidth + dstCX
                rotatedUV[dstUVIndex * 2] = u
                rotatedUV[dstUVIndex * 2 + 1] = v
            }
        }
    }
    
    // 从旋转后的图像中裁剪指定区域（使用重新计算的对齐后位置）

    // 裁剪 Y 平面
    var dstIndex = 0
    for (row in 0 until alignedCropHeight) {
        val srcRow = cropTop + row
        val srcIndex = srcRow * rotatedWidth + cropLeft
        System.arraycopy(rotatedY, srcIndex, nv12, dstIndex, alignedCropWidth)
        dstIndex += alignedCropWidth
    }

    // 裁剪 UV 平面
    val cropChromaLeft = cropLeft / 2
    val cropChromaTop = cropTop / 2
    val cropChromaWidth = alignedCropWidth / 2
    val cropChromaHeight = alignedCropHeight / 2

    var uvDstIndex = ySize
    for (row in 0 until cropChromaHeight) {
        val srcRow = cropChromaTop + row
        for (col in 0 until cropChromaWidth) {
            val srcCol = cropChromaLeft + col
            val uvSrcIndex = (srcRow * rotatedChromaWidth + srcCol) * 2
            nv12[uvDstIndex++] = rotatedUV[uvSrcIndex]      // U
            nv12[uvDstIndex++] = rotatedUV[uvSrcIndex + 1]  // V
        }
    }

    // 绘制时间戳（如果提供）
    if (timestamp != null) {
        drawTimestampOnNv12(nv12, alignedCropWidth, alignedCropHeight, timestamp, charWidth, charHeight)
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

private fun degreesToSurfaceRotation(degrees: Int): Int = when ((degrees % 360 + 360) % 360) {
    0 -> Surface.ROTATION_0
    90 -> Surface.ROTATION_90
    180 -> Surface.ROTATION_180
    270 -> Surface.ROTATION_270
    else -> Surface.ROTATION_0
}


data class WebSocketUiState(
    val url: String = "ws://39.98.165.184:50002/android-cam",
    val isConnected: Boolean = false,
    val isStreaming: Boolean = false,
    val statusMessage: String = "Disconnected",
    val qrHint: String? = null
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
            Box(
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
                    viewModel = webSocketViewModel,
                    deviceRotation = currentDeviceRotation
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
                Column {
                    Text(text = uiState.statusMessage)
                    uiState.qrHint?.let {
                        Text(
                            text = it,
                            color = Color(0xFFf5a623),
                            fontSize = 12.sp
                        )
                    }
                }
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
    deviceRotation: Int,
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
    LaunchedEffect(imageAnalysis, requestedAspectRatio, selectedCameraFacing, deviceRotation) {
        try {
            val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
            val cameraProvider = cameraProviderFuture.get()
            cameraProvider.unbindAll()
            val cameraSelector = when (selectedCameraFacing) {
                CameraCharacteristics.LENS_FACING_FRONT -> CameraSelector.DEFAULT_FRONT_CAMERA
                else -> CameraSelector.DEFAULT_BACK_CAMERA
            }

            // 预览沿用显示旋转，保持与屏幕方向一致，避免随物理旋转重复叠加
            val displayRotation = previewView.display.rotation
            val targetRotation = displayRotation

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
