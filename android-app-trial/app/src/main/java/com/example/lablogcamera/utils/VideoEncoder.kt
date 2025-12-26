package com.example.lablogcamera.utils

import android.annotation.SuppressLint
import android.graphics.Rect
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.util.Log
import androidx.camera.core.ImageProxy
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder

private const val TAG = "VideoEncoder"

/**
 * 视频编码器封装（支持 H.265/H.264）
 * 单段录制，最长 60 秒
 */
class VideoEncoder(
    private val preferH265: Boolean,
    private val onVideoComplete: (ByteArray, VideoMetadata) -> Unit
) {
    private var mediaCodec: MediaCodec? = null
    private var mediaMuxer: MediaMuxer? = null
    private var tempFile: File? = null
    private var videoTrackIndex: Int = -1
    private var isStarted: Boolean = false
    private var isFirstKeyframeReceived: Boolean = false
    
    var encoderWidth: Int = 0
        private set
    var encoderHeight: Int = 0
        private set
    var encoderFps: Int = 0
        private set
    var codecName: String = "H.264"
        private set
    private var encoderColorFormat: Int = MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar
    
    private var cachedSpsBuffer: ByteBuffer? = null
    private var cachedPpsBuffer: ByteBuffer? = null
    private var firstFrameTimeUs: Long = -1
    private var frameCount: Int = 0
    
    /**
     * 尝试根据 outputFormat 启动 muxer（需要有 csd-0）
     * 兼容老设备可能不触发 INFO_OUTPUT_FORMAT_CHANGED 的情况
     */
    private fun tryStartMuxerWithFormat(format: MediaFormat) {
        if (isStarted) return
        val muxer = mediaMuxer ?: return
        
        val csd0 = format.getByteBuffer("csd-0")
        val csd1 = format.getByteBuffer("csd-1")
        if (csd0 == null) {
            Log.w(TAG, "Muxer start skipped: csd-0 is null, wait for INFO_OUTPUT_FORMAT_CHANGED")
            return
        }
        
        cachedSpsBuffer = csd0.duplicate()
        cachedPpsBuffer = csd1?.duplicate()
        
        if (videoTrackIndex < 0) {
            videoTrackIndex = muxer.addTrack(format)
        }
        muxer.start()
        isStarted = true
        Log.d(TAG, "Video track added via tryStartMuxer, index=$videoTrackIndex, isStarted=$isStarted")
    }
    
    /**
     * 启动编码器
     * @param width 视频宽度
     * @param height 视频高度
     * @param bitrate 码率（bps）
     * @param targetFps 目标帧率
     */
    fun start(width: Int, height: Int, bitrate: Int, targetFps: Int) {
        encoderWidth = width
        encoderHeight = height
        encoderFps = if (targetFps > 0) targetFps else 10
        val frameRate = if (targetFps > 0) targetFps else 10
        
        // 尝试创建编码器（H.265 优先，失败回退 H.264）
        val (codec, codecType) = createVideoEncoder(preferH265)
        codecName = codecType
        
        val mimeType = if (codecType == "H.265") MediaFormat.MIMETYPE_VIDEO_HEVC else MediaFormat.MIMETYPE_VIDEO_AVC
        val mediaFormat = MediaFormat.createVideoFormat(mimeType, width, height).apply {
            setInteger(
                MediaFormat.KEY_COLOR_FORMAT,
                MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar
            )
            setInteger(MediaFormat.KEY_BIT_RATE, bitrate)
            setInteger(MediaFormat.KEY_FRAME_RATE, frameRate)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
            setInteger(MediaFormat.KEY_PREPEND_HEADER_TO_SYNC_FRAMES, 1)
        }
        
        Log.d(TAG, "Encoder config: ${width}x${height}, codec=$codecType")
        
        try {
            codec.configure(mediaFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            encoderColorFormat = codec.inputFormat?.getInteger(MediaFormat.KEY_COLOR_FORMAT)
                ?: MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar
            codec.start()
            mediaCodec = codec
            
            // 创建临时 MP4 文件
            tempFile = File.createTempFile("recording_", ".mp4")
            mediaMuxer = MediaMuxer(tempFile!!.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            
            // 尝试直接使用 outputFormat 启动 muxer；若失败则等待 INFO_OUTPUT_FORMAT_CHANGED
            try {
                val outputFormat = codec.outputFormat
                tryStartMuxerWithFormat(outputFormat)
            } catch (e: Exception) {
                Log.w(TAG, "Failed to get output format at start, will wait for INFO_OUTPUT_FORMAT_CHANGED", e)
            }
            
            Log.d(TAG, "$codecType Encoder started successfully, colorFormat=$encoderColorFormat")
        } catch (e: IOException) {
            Log.e(TAG, "Failed to create encoder", e)
            codec.release()
            throw e
        }
    }
    
    /**
     * 创建视频编码器（优先 H.265，失败回退 H.264）
     */
    private fun createVideoEncoder(preferH265: Boolean): Pair<MediaCodec, String> {
        if (preferH265) {
            try {
                val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_HEVC)
                return codec to "H.265"
            } catch (e: Exception) {
                Log.w(TAG, "H.265 not supported, fallback to H.264", e)
            }
        }
        val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        return codec to "H.264"
    }
    
    /**
     * 编码一帧
     */
    @SuppressLint("UnsafeOptInUsageError")
    fun encode(
        image: ImageProxy,
        cropRect: Rect,
        rotationDegrees: Int = 0,
        timestamp: String? = null,
        charWidth: Int = 20,
        charHeight: Int = 30
    ) {
        val codec = mediaCodec ?: return
        
        try {
            val nv12Bytes = image.toNv12ByteArray(cropRect, rotationDegrees, timestamp, charWidth, charHeight)
            
            // 计算实际的 YUV 数据大小（编码器期望的大小）
            val expectedSize = encoderWidth * encoderHeight * 3 / 2
            
            val yuvBytes = if (encoderColorFormat == MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Planar) {
                // 需要 I420 格式
                nv12ToI420(nv12Bytes, encoderWidth, encoderHeight)
            } else {
                // NV12 格式
                nv12Bytes
            }
            
            // 检查数据大小（Android 8.1 兼容性）
            if (yuvBytes.size != expectedSize) {
                Log.w(TAG, "YUV data size mismatch: expected=$expectedSize, actual=${yuvBytes.size}, ratio=${yuvBytes.size.toFloat()/expectedSize}")
                
                // 如果大小差异太大（<50%），可能是严重错误
                if (yuvBytes.size < expectedSize * 0.5) {
                    Log.e(TAG, "YUV data critically small (<50%), skipping frame")
                    return
                }
                
                // 调整数据大小（填充或截断）
                val adjustedBytes = ByteArray(expectedSize)
                System.arraycopy(yuvBytes, 0, adjustedBytes, 0, minOf(yuvBytes.size, expectedSize))
                
                // 如果数据不足，智能填充
                if (yuvBytes.size < expectedSize) {
                    val ySize = encoderWidth * encoderHeight
                    val uvStart = ySize
                    
                    // 如果Y平面不完整，填充为16（黑色）
                    if (yuvBytes.size < ySize) {
                        Log.w(TAG, "Y plane incomplete, padding with black")
                        for (i in yuvBytes.size until ySize) {
                            adjustedBytes[i] = 16
                        }
                        // UV平面全部填充为128（中性色）
                        for (i in uvStart until expectedSize) {
                            adjustedBytes[i] = 128.toByte()
                        }
                    } else {
                        // Y平面完整，只填充UV平面
                        Log.w(TAG, "UV plane incomplete, padding with neutral color")
                        for (i in yuvBytes.size until expectedSize) {
                            adjustedBytes[i] = 128.toByte()
                        }
                    }
                }
                
                val inputBufferIndex = codec.dequeueInputBuffer(10000)
                if (inputBufferIndex >= 0) {
                    val inputBuffer = codec.getInputBuffer(inputBufferIndex)
                    if (inputBuffer != null) {
                        inputBuffer.clear()
                        if (inputBuffer.capacity() < adjustedBytes.size) {
                            Log.e(TAG, "Encoder input buffer too small: capacity=${inputBuffer.capacity()}, data=${adjustedBytes.size}")
                            return
                        }
                        inputBuffer.put(adjustedBytes)
                    }
                    val presentationTimeUs = image.imageInfo.timestamp / 1000L
                    codec.queueInputBuffer(inputBufferIndex, 0, adjustedBytes.size, presentationTimeUs, 0)
                }
            } else {
                val inputBufferIndex = codec.dequeueInputBuffer(10000)
                if (inputBufferIndex >= 0) {
                    val inputBuffer = codec.getInputBuffer(inputBufferIndex)
                    if (inputBuffer != null) {
                        inputBuffer.clear()
                        if (inputBuffer.capacity() < yuvBytes.size) {
                            Log.e(TAG, "Encoder input buffer too small: capacity=${inputBuffer.capacity()}, data=${yuvBytes.size}")
                            return
                        }
                        inputBuffer.put(yuvBytes)
                    }
                    val presentationTimeUs = image.imageInfo.timestamp / 1000L
                    codec.queueInputBuffer(inputBufferIndex, 0, yuvBytes.size, presentationTimeUs, 0)
                }
            }
            
            val bufferInfo = MediaCodec.BufferInfo()
            var outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
            
            while (outputBufferIndex >= 0) {
                when (outputBufferIndex) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        val format = codec.outputFormat
                        Log.d(TAG, "Output format changed: $format")
                        tryStartMuxerWithFormat(format)
                        outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
                        continue
                    }
                    MediaCodec.INFO_TRY_AGAIN_LATER -> {
                        Log.v(TAG, "dequeueOutputBuffer: try again later")
                        break
                    }
                    MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED -> {
                        Log.d(TAG, "Output buffers changed")
                        outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
                        continue
                    }
                    else -> {
                        // 正常的输出缓冲区
                        val outputBuffer = codec.getOutputBuffer(outputBufferIndex)
                        if (outputBuffer != null && bufferInfo.size > 0) {
                            val isKeyframe = (bufferInfo.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0
                            val isConfig = (bufferInfo.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0
                            
                            if (!isFirstKeyframeReceived && isKeyframe) {
                                isFirstKeyframeReceived = true
                                Log.d(TAG, "First keyframe received")
                            }
                            
                            // 兜底：如果 muxer 还没启动，尝试使用当前 format 或 codec-config buffer 启动
                            if (!isStarted) {
                                tryStartMuxerWithFormat(codec.outputFormat)
                                
                                if (!isStarted && isConfig) {
                                    try {
                                        // 部分设备将 SPS/PPS 放在 codec-config buffer 中
                                        outputBuffer.position(bufferInfo.offset)
                                        outputBuffer.limit(bufferInfo.offset + bufferInfo.size)
                                        val csdBuf = ByteBuffer.allocate(bufferInfo.size)
                                        csdBuf.put(outputBuffer)
                                        csdBuf.flip()
                                        
                                        val fallbackFormat = codec.outputFormat
                                        fallbackFormat.setByteBuffer("csd-0", csdBuf)
                                        tryStartMuxerWithFormat(fallbackFormat)
                                    } catch (e: Exception) {
                                        Log.w(TAG, "Failed to start muxer from codec-config buffer", e)
                                    }
                                }
                                
                                // 仍未启动且拿到关键帧时，强制使用当前 outputFormat 启动（无 csd 也启动，避免全程丢帧）
                                if (!isStarted && isKeyframe) {
                                    try {
                                        tryStartMuxerWithFormat(codec.outputFormat)
                                    } catch (e: Exception) {
                                        Log.e(TAG, "Forced muxer start failed", e)
                                    }
                                }
                            }
                            
                            // 写入 MP4
                            if (isStarted && videoTrackIndex >= 0) {
                                if (firstFrameTimeUs < 0) {
                                    firstFrameTimeUs = bufferInfo.presentationTimeUs
                                }
                                
                                // 直接使用 outputBuffer，不要重新分配
                                outputBuffer.position(bufferInfo.offset)
                                outputBuffer.limit(bufferInfo.offset + bufferInfo.size)
                                
                                try {
                                    mediaMuxer?.writeSampleData(videoTrackIndex, outputBuffer, bufferInfo)
                                    frameCount++
                                    if (frameCount == 1 || frameCount % 10 == 0) {
                                        Log.d(TAG, "Written $frameCount frames")
                                    }
                                } catch (e: Exception) {
                                    Log.e(TAG, "Failed to write frame $frameCount", e)
                                }
                            } else {
                                Log.w(TAG, "Skipping frame: isStarted=$isStarted, videoTrackIndex=$videoTrackIndex")
                            }
                        }
                        codec.releaseOutputBuffer(outputBufferIndex, false)
                        outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
                    }
                }
            }
        } catch (e: Exception) {
            if (e !is IllegalStateException) {
                Log.e(TAG, "Encoding error", e)
            }
        }
    }
    
    /**
     * 停止编码并获取完整的 MP4 数据
     */
    fun stop(): Pair<ByteArray, VideoMetadata>? {
        return try {
            val codec = mediaCodec
            
            Log.d(TAG, "Stopping encoder, frames written so far: $frameCount")
            
            // 1. 发送 EOS 信号给编码器
            if (codec != null) {
                try {
                    val inputBufferIndex = codec.dequeueInputBuffer(10000)
                    if (inputBufferIndex >= 0) {
                        codec.queueInputBuffer(
                            inputBufferIndex, 
                            0, 
                            0, 
                            System.nanoTime() / 1000, 
                            MediaCodec.BUFFER_FLAG_END_OF_STREAM
                        )
                        Log.d(TAG, "EOS signal sent to encoder")
                    }
                    
                    // 2. 等待 EOS 从编码器返回（在 encode() 线程中处理）
                    // 给编码器一些时间处理最后的帧
                    Thread.sleep(500)
                    
                } catch (e: Exception) {
                    Log.w(TAG, "Failed to send EOS", e)
                }
            }
            
            Log.d(TAG, "Total frames written: $frameCount")
            
            // 3. 停止 Muxer
            if (isStarted) {
                try {
                    mediaMuxer?.stop()
                    Log.d(TAG, "Muxer stopped")
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to stop muxer (this may happen on older Android versions): ${e.message}", e)
                    // 在旧版本Android上，如果缺少codec specific data，stop()会失败
                    // 这种情况下，直接release可能会生成不完整但可播放的文件
                }
            }
            
            try {
                mediaMuxer?.release()
                Log.d(TAG, "Muxer released")
            } catch (e: Exception) {
                Log.e(TAG, "Failed to release muxer", e)
            }
            mediaMuxer = null
            
            // 4. 停止编码器
            mediaCodec?.let { c ->
                try {
                    c.stop()
                    c.release()
                } catch (e: IllegalStateException) {
                    Log.w(TAG, "Codec stop/release skipped", e)
                }
            }
            mediaCodec = null
            
            // 5. 读取 MP4 数据
            val mp4Data = tempFile?.readBytes()
            val metadata = VideoMetadata(
                width = encoderWidth,
                height = encoderHeight,
                fps = encoderFps.toFloat(),
                codec = codecName,
                frameCount = frameCount
            )
            
            Log.d(TAG, "MP4 file size: ${mp4Data?.size ?: 0} bytes, path: ${tempFile?.absolutePath}")
            
            // 6. 清理临时文件
            tempFile?.delete()
            tempFile = null
            
            // 7. 重置状态
            isFirstKeyframeReceived = false
            videoTrackIndex = -1
            isStarted = false
            firstFrameTimeUs = -1
            frameCount = 0
            
            if (mp4Data != null && mp4Data.isNotEmpty()) {
                mp4Data to metadata
            } else {
                Log.e(TAG, "MP4 data is empty or null")
                null
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping encoder", e)
            null
        }
    }
    
    data class VideoMetadata(
        val width: Int,
        val height: Int,
        val fps: Float,
        val codec: String,
        val frameCount: Int
    )
}

/**
 * 将 NV12 转为 I420（Y + U + V 平面），用于只支持 YUV420Planar 的编码器
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
 * ImageProxy 扩展函数：转换为 NV12 字节数组
 * 复用自 MainActivity.kt，支持旋转和时间戳水印
 */
@SuppressLint("UnsafeOptInUsageError")
fun ImageProxy.toNv12ByteArray(
    cropRect: Rect,
    rotationDegrees: Int = 0,
    timestamp: String? = null,
    charWidth: Int = 20,
    charHeight: Int = 30
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
        val uBufferSize = uBuffer.capacity()
        val vBufferSize = vBuffer.capacity()
        
        try {
            for (row in 0 until chromaHeight) {
                val uRowStart = (row + chromaTop) * uRowStride
                val vRowStart = (row + chromaTop) * vRowStride
                for (col in 0 until chromaWidth) {
                    val uIndex = uRowStart + (col + chromaLeft) * uPixelStride
                    val vIndex = vRowStart + (col + chromaLeft) * vPixelStride
                    
                    // 边界检查（兼容Android 8.1）
                    if (uIndex >= 0 && uIndex < uBufferSize && 
                        vIndex >= 0 && vIndex < vBufferSize && 
                        uvDstIndex < nv12.size - 1) {
                        nv12[uvDstIndex++] = uBuffer.get(uIndex)
                        nv12[uvDstIndex++] = vBuffer.get(vIndex)
                    } else {
                        // 超出范围，填充中性色
                        if (uvDstIndex < nv12.size - 1) {
                            nv12[uvDstIndex++] = 128.toByte()
                            nv12[uvDstIndex++] = 128.toByte()
                        }
                    }
                }
            }
        } catch (e: Exception) {
            // 如果UV提取失败，填充剩余部分为中性色
            Log.w("VideoEncoder", "UV extraction failed, filling with neutral color", e)
            while (uvDstIndex < nv12.size) {
                nv12[uvDstIndex++] = 128.toByte()
            }
        }
        
        // 绘制时间戳（如果提供）
        if (timestamp != null) {
            drawTimestampOnNv12(nv12, cropWidth, cropHeight, timestamp, charWidth, charHeight)
        }
        
        return nv12
    }
    
    // 需要旋转的逻辑（复用 MainActivity.kt 逻辑）
    val (rotatedWidth, rotatedHeight) = when (rotationDegrees) {
        90, 270 -> Pair(imageHeight, imageWidth)
        0, 180 -> Pair(imageWidth, imageHeight)
        else -> Pair(imageWidth, imageHeight)
    }
    
    // 旋转时，为避免尺寸对齐导致的数据截断，直接使用旋转后的完整尺寸
    val alignedCropWidth = if (rotatedWidth % 2 == 0) rotatedWidth else rotatedWidth - 1
    val alignedCropHeight = if (rotatedHeight % 2 == 0) rotatedHeight else rotatedHeight - 1
    
    val cropLeft = 0
    val cropTop = 0
    
    val ySize = alignedCropWidth * alignedCropHeight
    val uvSize = ySize / 2
    val nv12 = ByteArray(ySize + uvSize)
    
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
    
    val rotatedYSize = rotatedWidth * rotatedHeight
    val rotatedY = ByteArray(rotatedYSize)
    val rotatedUVSize = rotatedYSize / 2
    val rotatedUV = ByteArray(rotatedUVSize)
    
    // 旋转 Y 平面（添加边界检查）
    val yBufferSize = yBuffer.capacity()
    for (y in 0 until imageHeight) {
        for (x in 0 until imageWidth) {
            val srcIndex = y * yRowStride + x
            if (srcIndex >= 0 && srcIndex < yBufferSize) {
                val srcY = yBuffer.get(srcIndex)
                
                val (dstX, dstY) = when (rotationDegrees) {
                    90 -> Pair(imageHeight - 1 - y, x)
                    180 -> Pair(imageWidth - 1 - x, imageHeight - 1 - y)
                    270 -> Pair(y, imageWidth - 1 - x)
                    else -> Pair(x, y)
                }
                
                if (dstX in 0 until rotatedWidth && dstY in 0 until rotatedHeight) {
                    val dstIndex = dstY * rotatedWidth + dstX
                    if (dstIndex >= 0 && dstIndex < rotatedY.size) {
                        rotatedY[dstIndex] = srcY
                    }
                }
            }
        }
    }
    
    // 旋转 UV 平面（添加边界检查）
    val chromaWidth = imageWidth / 2
    val chromaHeight = imageHeight / 2
    val rotatedChromaWidth = rotatedWidth / 2
    val rotatedChromaHeight = rotatedHeight / 2
    val uBufferSize = uBuffer.capacity()
    val vBufferSize = vBuffer.capacity()
    
    for (cy in 0 until chromaHeight) {
        for (cx in 0 until chromaWidth) {
            val uIndex = cy * uRowStride + cx * uPixelStride
            val vIndex = cy * vRowStride + cx * vPixelStride
            
            if (uIndex >= 0 && uIndex < uBufferSize && 
                vIndex >= 0 && vIndex < vBufferSize) {
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
                    if (dstUVIndex * 2 + 1 < rotatedUV.size) {
                        rotatedUV[dstUVIndex * 2] = u
                        rotatedUV[dstUVIndex * 2 + 1] = v
                    }
                }
            } else {
                // 如果UV数据超出边界，使用中性色填充对应位置
                val (dstCX, dstCY) = when (rotationDegrees) {
                    90 -> Pair(chromaHeight - 1 - cy, cx)
                    180 -> Pair(chromaWidth - 1 - cx, chromaHeight - 1 - cy)
                    270 -> Pair(cy, chromaWidth - 1 - cx)
                    else -> Pair(cx, cy)
                }
                
                if (dstCX in 0 until rotatedChromaWidth && dstCY in 0 until rotatedChromaHeight) {
                    val dstUVIndex = dstCY * rotatedChromaWidth + dstCX
                    if (dstUVIndex * 2 + 1 < rotatedUV.size) {
                        rotatedUV[dstUVIndex * 2] = 128.toByte()
                        rotatedUV[dstUVIndex * 2 + 1] = 128.toByte()
                    }
                }
            }
        }
    }
    
    // 裁剪
    var dstIndex = 0
    for (row in 0 until alignedCropHeight) {
        val srcRow = cropTop + row
        val srcIndex = srcRow * rotatedWidth + cropLeft
        System.arraycopy(rotatedY, srcIndex, nv12, dstIndex, alignedCropWidth)
        dstIndex += alignedCropWidth
    }
    
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
            nv12[uvDstIndex++] = rotatedUV[uvSrcIndex]
            nv12[uvDstIndex++] = rotatedUV[uvSrcIndex + 1]
        }
    }
    
    // 绘制时间戳
    if (timestamp != null) {
        drawTimestampOnNv12(nv12, alignedCropWidth, alignedCropHeight, timestamp, charWidth, charHeight)
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

/**
 * 应用分辨率上限裁剪
 * 如果 width 或 height 超过 limit，裁剪为 limit x limit 的正方形
 * 否则不裁剪
 */
fun applyResolutionLimit(width: Int, height: Int, limit: Int): Pair<Int, Int> {
    if (width <= limit && height <= limit) {
        return width to height
    }
    // 裁剪为正方形
    val size = minOf(width, height, limit)
    return size to size
}

