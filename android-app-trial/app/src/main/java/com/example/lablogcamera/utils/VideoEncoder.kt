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
            val yuvBytes = if (encoderColorFormat == MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Planar) {
                nv12ToI420(nv12Bytes, cropRect.width(), cropRect.height())
            } else {
                nv12Bytes
            }
            
            val inputBufferIndex = codec.dequeueInputBuffer(10000)
            if (inputBufferIndex >= 0) {
                val inputBuffer = codec.getInputBuffer(inputBufferIndex)
                if (inputBuffer != null) {
                    inputBuffer.clear()
                    if (inputBuffer.capacity() < yuvBytes.size) {
                        Log.e(TAG, "Encoder input buffer too small")
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
                if (outputBufferIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    val format = codec.outputFormat
                    val csd0 = format.getByteBuffer("csd-0")
                    val csd1 = format.getByteBuffer("csd-1")
                    if (csd0 != null) {
                        cachedSpsBuffer = csd0.duplicate()
                        cachedPpsBuffer = csd1?.duplicate()
                        
                        // 添加视频轨道
                        if (videoTrackIndex < 0) {
                            videoTrackIndex = mediaMuxer?.addTrack(format) ?: -1
                            mediaMuxer?.start()
                            isStarted = true
                            Log.d(TAG, "Video track added, index=$videoTrackIndex")
                        }
                    }
                    outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
                    continue
                }
                
                val outputBuffer = codec.getOutputBuffer(outputBufferIndex)
                if (outputBuffer != null && bufferInfo.size > 0) {
                    val encodedData = ByteArray(bufferInfo.size)
                    outputBuffer.get(encodedData)
                    
                    val isKeyframe = (bufferInfo.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0
                    
                    if (!isFirstKeyframeReceived && isKeyframe) {
                        isFirstKeyframeReceived = true
                        Log.d(TAG, "First keyframe received")
                    }
                    
                    // 写入 MP4
                    if (isStarted && videoTrackIndex >= 0) {
                        if (firstFrameTimeUs < 0) {
                            firstFrameTimeUs = bufferInfo.presentationTimeUs
                        }
                        
                        val buffer = ByteBuffer.allocate(bufferInfo.size)
                        buffer.put(encodedData)
                        buffer.position(bufferInfo.offset)
                        buffer.limit(bufferInfo.offset + bufferInfo.size)
                        mediaMuxer?.writeSampleData(videoTrackIndex, buffer, bufferInfo)
                        frameCount++
                    }
                }
                codec.releaseOutputBuffer(outputBufferIndex, false)
                outputBufferIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)
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
            // 停止 Muxer
            if (isStarted) {
                mediaMuxer?.stop()
            }
            mediaMuxer?.release()
            mediaMuxer = null
            
            // 停止编码器
            mediaCodec?.let { codec ->
                try {
                    codec.stop()
                    codec.release()
                } catch (e: IllegalStateException) {
                    Log.w(TAG, "Codec stop/release skipped", e)
                }
            }
            mediaCodec = null
            
            // 读取 MP4 数据
            val mp4Data = tempFile?.readBytes()
            val metadata = VideoMetadata(
                width = encoderWidth,
                height = encoderHeight,
                fps = encoderFps.toFloat(),
                codec = codecName,
                frameCount = frameCount
            )
            
            // 清理临时文件
            tempFile?.delete()
            tempFile = null
            
            // 重置状态
            isFirstKeyframeReceived = false
            videoTrackIndex = -1
            isStarted = false
            firstFrameTimeUs = -1
            frameCount = 0
            
            if (mp4Data != null && mp4Data.isNotEmpty()) {
                mp4Data to metadata
            } else {
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
    
    // 需要旋转的逻辑（复用 MainActivity.kt 逻辑）
    val (rotatedWidth, rotatedHeight) = when (rotationDegrees) {
        90, 270 -> Pair(imageHeight, imageWidth)
        0, 180 -> Pair(imageWidth, imageHeight)
        else -> Pair(imageWidth, imageHeight)
    }
    
    val safeRect = cropRect.ensureEvenBounds(rotatedWidth, rotatedHeight)
    val cropWidth = safeRect.width()
    val cropHeight = safeRect.height()
    
    val alignedCropWidth = ((cropWidth / 32) * 32).let { if (it % 2 != 0) it - 1 else it }.coerceAtLeast(2)
    val alignedCropHeight = ((cropHeight / 32) * 32).let { if (it % 2 != 0) it - 1 else it }.coerceAtLeast(2)
    
    val originalCenterX = safeRect.left + cropWidth / 2
    val originalCenterY = safeRect.top + cropHeight / 2
    val cropLeft = (originalCenterX - alignedCropWidth / 2).coerceIn(0, rotatedWidth - alignedCropWidth)
    val cropTop = (originalCenterY - alignedCropHeight / 2).coerceIn(0, rotatedHeight - alignedCropHeight)
    
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
    
    // 旋转 Y 平面
    for (y in 0 until imageHeight) {
        for (x in 0 until imageWidth) {
            val srcIndex = y * yRowStride + x
            val srcY = yBuffer.get(srcIndex)
            
            val (dstX, dstY) = when (rotationDegrees) {
                90 -> Pair(imageHeight - 1 - y, x)
                180 -> Pair(imageWidth - 1 - x, imageHeight - 1 - y)
                270 -> Pair(y, imageWidth - 1 - x)
                else -> Pair(x, y)
            }
            
            if (dstX in 0 until rotatedWidth && dstY in 0 until rotatedHeight) {
                val dstIndex = dstY * rotatedWidth + dstX
                rotatedY[dstIndex] = srcY
            }
        }
    }
    
    // 旋转 UV 平面
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

