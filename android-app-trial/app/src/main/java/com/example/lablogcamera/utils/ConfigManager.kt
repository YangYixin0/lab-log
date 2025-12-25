package com.example.lablogcamera.utils

import android.content.Context
import android.util.Log
import java.io.IOException
import java.util.Properties

/**
 * 配置管理器
 * 从 assets/config.properties 读取配置
 */
object ConfigManager {
    private const val TAG = "ConfigManager"
    private const val CONFIG_FILE = "config.properties"
    
    private var properties: Properties? = null
    
    /**
     * 初始化配置管理器
     * 应在 Application 或 Activity 启动时调用
     */
    fun initialize(context: Context) {
        if (properties != null) return
        
        try {
            properties = Properties().apply {
                context.assets.open(CONFIG_FILE).use { inputStream ->
                    load(inputStream)
                }
            }
            Log.d(TAG, "Config loaded successfully")
        } catch (e: IOException) {
            Log.e(TAG, "Failed to load config file", e)
            properties = Properties() // 使用空配置避免 NPE
        }
    }
    
    private fun getProperty(key: String, defaultValue: String): String {
        return properties?.getProperty(key, defaultValue) ?: defaultValue
    }
    
    // API 配置
    val apiKey: String
        get() = getProperty("dashscope_api_key", "")
    
    val qwenModel: String
        get() = getProperty("qwen_model", "qwen3-vl-flash")
    
    // 视频参数
    val videoResolutionLimit: Int
        get() = getProperty("video_resolution_limit", "1920").toIntOrNull() ?: 1920
    
    val videoBitrateMbps: Float
        get() = getProperty("video_bitrate_mbps", "2.0").toFloatOrNull() ?: 2.0f
    
    val videoFps: Int
        get() = getProperty("video_fps", "4").toIntOrNull() ?: 4
    
    val videoMaxDurationSeconds: Int
        get() = getProperty("video_max_duration_seconds", "60").toIntOrNull() ?: 60
    
    // 编码格式优先级
    val videoCodecPriority: List<String>
        get() = getProperty("video_codec_priority", "h265,h264")
            .split(",")
            .map { it.trim() }
    
    val preferH265: Boolean
        get() = videoCodecPriority.firstOrNull()?.equals("h265", ignoreCase = true) ?: false
    
    // 使用次数限制
    val maxApiCalls: Int
        get() = getProperty("max_api_calls", "10").toIntOrNull() ?: 10
    
    // 超时设置
    val apiTimeoutMs: Long
        get() = getProperty("api_timeout_ms", "120000").toLongOrNull() ?: 120000L
}

