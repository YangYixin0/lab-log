package com.example.lablogcamera.data

/**
 * 录制记录
 */
data class RecordingItem(
    val id: String,  // 时间戳，如 "20250126_143052"
    val videoPath: String,
    val thumbnailPath: String?,
    val duration: Long,  // 毫秒
    val resolution: String,  // "1920x1920"
    val fps: Float,
    val bitrate: Float,  // Mbps
    val codec: String,  // "H.264" 或 "H.265"
    val createdAt: Long,  // 时间戳（毫秒）
    val results: List<UnderstandingResult> = emptyList()
)

/**
 * 理解结果
 */
data class UnderstandingResult(
    val id: String,  // 唯一ID
    val timestamp: Long,  // 创建时间戳（毫秒）
    val prompt: String,  // 使用的提示词
    val events: List<Event>,
    val appearances: List<Appearance>,
    val rawResponse: String,  // 原始响应
    val isStreaming: Boolean = false  // 是否正在流式输出
)

/**
 * 事件
 */
data class Event(
    val eventId: String,  // evt_00001
    val startTime: String,  // "hh:mm:ss"
    val endTime: String,  // "hh:mm:ss"
    val eventType: String,  // "person" / "equipment-only" / "none"
    val personIds: List<String>,  // ["p1", "p2"]
    val equipment: String,  // 设备名称
    val description: String  // 事件描述
)

/**
 * 人物外貌
 */
data class Appearance(
    val personId: String,  // p1, p2...
    val features: String  // JSON格式的外貌特征
)

/**
 * CSV 导出工具
 */
object CsvExporter {
    /**
     * 将事件列表转为 CSV 格式
     */
    fun eventsToCSV(events: List<Event>): String {
        val header = "开始时间,结束时间,事件类型,人物编号,设备,描述\n"
        val rows = events.joinToString("\n") { event ->
            val personIdsStr = event.personIds.joinToString(";")
            "${event.startTime},${event.endTime},${event.eventType},$personIdsStr,${event.equipment},\"${event.description.replace("\"", "\"\"")}\""
        }
        return header + rows
    }
    
    /**
     * 将人物外貌列表转为 CSV 格式
     */
    fun appearancesToCSV(appearances: List<Appearance>): String {
        val header = "人物编号,外貌特征\n"
        val rows = appearances.joinToString("\n") { appearance ->
            "${appearance.personId},\"${appearance.features.replace("\"", "\"\"")}\""
        }
        return header + rows
    }
}

