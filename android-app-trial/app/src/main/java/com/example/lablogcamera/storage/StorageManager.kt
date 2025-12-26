package com.example.lablogcamera.storage

import android.content.Context
import android.graphics.Bitmap
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.util.Log
import com.example.lablogcamera.data.RecordingItem
import com.example.lablogcamera.data.UnderstandingResult
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 存储管理器
 * 管理视频文件、缩略图和 JSON 结果的存储
 */
class StorageManager(private val context: Context) {
    private val gson = Gson()
    
    companion object {
        private const val TAG = "StorageManager"
        private const val VIDEOS_DIR = "videos"
        private const val RESULTS_DIR = "results"
        private const val THUMBNAILS_DIR = "thumbnails"
        private const val TIMESTAMP_FORMAT = "yyyyMMdd_HHmmss"
    }
    
    private val videosDir: File
        get() = File(context.filesDir, VIDEOS_DIR).also { it.mkdirs() }
    
    private val resultsDir: File
        get() = File(context.filesDir, RESULTS_DIR).also { it.mkdirs() }
    
    private val thumbnailsDir: File
        get() = File(context.filesDir, THUMBNAILS_DIR).also { it.mkdirs() }
    
    /**
     * 生成基于时间戳的唯一 ID
     */
    fun generateId(): String {
        val sdf = SimpleDateFormat(TIMESTAMP_FORMAT, Locale.getDefault())
        return sdf.format(Date())
    }
    
    /**
     * 保存视频文件
     * @param id 录制ID
     * @param videoData 视频数据
     * @return 视频文件路径
     */
    fun saveVideo(id: String, videoData: ByteArray): String {
        val videoFile = File(videosDir, "$id.mp4")
        videoFile.writeBytes(videoData)
        Log.d(TAG, "Video saved: ${videoFile.absolutePath}, size=${videoData.size}")
        return videoFile.absolutePath
    }
    
    /**
     * 生成视频缩略图
     * @param videoPath 视频文件路径
     * @param id 录制ID
     * @return 缩略图文件路径，如果失败返回 null
     */
    fun generateThumbnail(videoPath: String, id: String): String? {
        return try {
            val retriever = MediaMetadataRetriever()
            retriever.setDataSource(videoPath)
            
            // 获取第一帧
            val bitmap = retriever.getFrameAtTime(0)
            retriever.release()
            
            if (bitmap != null) {
                val thumbnailFile = File(thumbnailsDir, "$id.jpg")
                FileOutputStream(thumbnailFile).use { out ->
                    bitmap.compress(Bitmap.CompressFormat.JPEG, 80, out)
                }
                bitmap.recycle()
                Log.d(TAG, "Thumbnail generated: ${thumbnailFile.absolutePath}")
                thumbnailFile.absolutePath
            } else {
                null
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to generate thumbnail", e)
            null
        }
    }
    
    /**
     * 获取视频时长（毫秒）
     */
    fun getVideoDuration(videoPath: String): Long {
        return try {
            val retriever = MediaMetadataRetriever()
            retriever.setDataSource(videoPath)
            val duration = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            retriever.release()
            duration
        } catch (e: Exception) {
            Log.e(TAG, "Failed to get video duration", e)
            0L
        }
    }
    
    /**
     * 保存理解结果
     * @param id 录制ID
     * @param results 理解结果列表
     */
    fun saveResults(id: String, results: List<UnderstandingResult>) {
        val resultFile = File(resultsDir, "$id.json")
        val json = gson.toJson(results)
        resultFile.writeText(json)
        Log.d(TAG, "Results saved: ${resultFile.absolutePath}")
    }
    
    /**
     * 读取理解结果
     * @param id 录制ID
     * @return 理解结果列表，如果不存在返回空列表
     */
    fun loadResults(id: String): List<UnderstandingResult> {
        val resultFile = File(resultsDir, "$id.json")
        return if (resultFile.exists()) {
            try {
                val json = resultFile.readText()
                val type = object : TypeToken<List<UnderstandingResult>>() {}.type
                gson.fromJson(json, type) ?: emptyList()
            } catch (e: Exception) {
                Log.e(TAG, "Failed to load results", e)
                emptyList()
            }
        } else {
            emptyList()
        }
    }
    
    /**
     * 列出所有录制记录
     * @return 录制记录列表，按时间倒序排列
     */
    fun listRecordings(): List<RecordingItem> {
        val recordings = mutableListOf<RecordingItem>()
        
        videosDir.listFiles { file -> file.extension == "mp4" }?.forEach { videoFile ->
            val id = videoFile.nameWithoutExtension
            val videoPath = videoFile.absolutePath
            val thumbnailPath = File(thumbnailsDir, "$id.jpg").let {
                if (it.exists()) it.absolutePath else null
            }
            
            // 获取视频元数据
            val duration = getVideoDuration(videoPath)
            val (width, height, fps, bitrate, codec) = getVideoMetadata(videoPath)
            
            // 加载理解结果
            val results = loadResults(id)
            
            recordings.add(
                RecordingItem(
                    id = id,
                    videoPath = videoPath,
                    thumbnailPath = thumbnailPath,
                    duration = duration,
                    resolution = "${width}x${height}",
                    fps = fps,
                    bitrate = bitrate,
                    codec = codec,
                    createdAt = videoFile.lastModified(),
                    results = results
                )
            )
        }
        
        // 按创建时间倒序排列
        return recordings.sortedByDescending { it.createdAt }
    }
    
    /**
     * 获取视频元数据
     * @return (width, height, fps, bitrate_mbps, codec)
     */
    private fun getVideoMetadata(videoPath: String): VideoMetadata {
        return try {
            val retriever = MediaMetadataRetriever()
            retriever.setDataSource(videoPath)
            
            val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() ?: 0
            val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull() ?: 0
            val bitrate = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_BITRATE)?.toLongOrNull() ?: 0L
            val bitrateMbps = bitrate / 1_000_000f
            
            // 使用 MediaExtractor 获取真实帧率
            var fps = 0f
            try {
                val extractor = MediaExtractor()
                extractor.setDataSource(videoPath)
                
                // 查找视频轨道
                for (i in 0 until extractor.trackCount) {
                    val format = extractor.getTrackFormat(i)
                    val mime = format.getString(MediaFormat.KEY_MIME) ?: ""
                    if (mime.startsWith("video/")) {
                        // 尝试从 format 中获取帧率
                        if (format.containsKey(MediaFormat.KEY_FRAME_RATE)) {
                            fps = format.getInteger(MediaFormat.KEY_FRAME_RATE).toFloat()
                        }
                        break
                    }
                }
                extractor.release()
            } catch (e: Exception) {
                Log.w(TAG, "Failed to extract frame rate using MediaExtractor", e)
            }
            
            // 检测编码格式
            val mimeType = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_MIMETYPE) ?: ""
            val codec = when {
                mimeType.contains("hevc", ignoreCase = true) || mimeType.contains("h265", ignoreCase = true) -> "H.265"
                else -> "H.264"
            }
            
            retriever.release()
            VideoMetadata(width, height, fps, bitrateMbps, codec)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to get video metadata", e)
            VideoMetadata(0, 0, 0f, 0f, "Unknown")
        }
    }
    
    /**
     * 删除录制记录（包括视频、缩略图和结果）
     * @param id 录制ID
     */
    fun deleteRecording(id: String) {
        // 删除视频
        File(videosDir, "$id.mp4").delete()
        // 删除缩略图
        File(thumbnailsDir, "$id.jpg").delete()
        // 删除结果
        File(resultsDir, "$id.json").delete()
        Log.d(TAG, "Recording deleted: $id")
    }
    
    /**
     * 获取录制记录
     * @param id 录制ID
     * @return 录制记录，如果不存在返回 null
     */
    fun getRecording(id: String): RecordingItem? {
        val videoFile = File(videosDir, "$id.mp4")
        if (!videoFile.exists()) return null
        
        val videoPath = videoFile.absolutePath
        val thumbnailPath = File(thumbnailsDir, "$id.jpg").let {
            if (it.exists()) it.absolutePath else null
        }
        
        val duration = getVideoDuration(videoPath)
        val (width, height, fps, bitrate, codec) = getVideoMetadata(videoPath)
        val results = loadResults(id)
        
        return RecordingItem(
            id = id,
            videoPath = videoPath,
            thumbnailPath = thumbnailPath,
            duration = duration,
            resolution = "${width}x${height}",
            fps = fps,
            bitrate = bitrate,
            codec = codec,
            createdAt = videoFile.lastModified(),
            results = results
        )
    }
    
    data class VideoMetadata(
        val width: Int,
        val height: Int,
        val fps: Float,
        val bitrateMbps: Float,
        val codec: String
    )
}

