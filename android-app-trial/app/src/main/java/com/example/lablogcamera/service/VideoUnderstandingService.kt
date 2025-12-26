package com.example.lablogcamera.service

import android.util.Base64
import android.util.Log
import com.example.lablogcamera.data.Appearance
import com.example.lablogcamera.data.Event
import com.example.lablogcamera.data.UnderstandingResult
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.BufferedReader
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

private const val TAG = "VideoUnderstandingService"

/**
 * 视频理解服务
 * 调用阿里云 Qwen3-VL API 进行视频理解
 */
class VideoUnderstandingService(
    private val apiKey: String,
    private val model: String = "qwen3-vl-flash",
    private val timeoutMs: Long = 120000L,
    private val videoFps: Float = 2.0f,
    private val enableThinking: Boolean = true,
    private val thinkingBudget: Int = 8192,
    private val highResolutionImages: Boolean = true,
    private val temperature: Float = 0.1f,
    private val topP: Float = 0.7f
) {
    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()
    
    companion object {
        private const val API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        
        // 默认提示词
        const val DEFAULT_PROMPT = """请分析这段实验室视频，识别人物动作和设备操作。

输出要求：
1. 输出完整的事件表（events数组），每个事件包含：
   - event_id: 事件编号（evt_01、evt_02...）
   - start_time: 开始时间（从视频左上角时间戳水印读取，格式hh:mm:ss）
   - end_time: 结束时间
   - event_type: 事件类型（person/equipment-only/none）
   - person_ids: 人物编号数组（["p1", "p2"]）
   - equipment: 设备名称
   - description: 事件描述

2. 输出完整的人物外貌表（appearances数组），每个人物包含：
   - person_id: 人物编号（p1、p2...）
   - features: 外貌特征（字符串格式）

输出格式为纯JSON：
{
  "events": [...],
  "appearances": [...]
}

任务要求：
- 识别视频中人物进入或离开画面（是否携带物品）、人物操作设备或化学品、设备状态变化，raw_text 字段可以很详细。
- 关于时间
  - 根据视频画面左上角的时间戳水印确定时间
  - 一个视频片段内，可能发生多个事件。
  - 不同事件的时间范围可以有部分或完全重叠。例如，如果画面中同时出现某个人物和某个显示数值的设备，而且人物动作和设备状态变化是独立的，那么这两个事件应当分开记录而且有部分或完全的重叠时间范围。
- 关于 person 事件
  - person 事件中，如果人物操作了什么设备，那么 equipment 字段应当记录该设备名称。如果人物没有操作设备，那么 equipment 字段应当为空字符串。
  - **同一个人连续未操作设备或操作同一个设备时，应当合并为一个事件，描述可以长一些。**
  - 注意描述人物**把什么物品从哪个容器取出**，或者**把什么物品放进哪个容器**。人物从同一个容器可能取出物品，也可能放入物品，关键在于**人物的手上是多了物品还是少了物品**。
  - 如果画面内存在多个相似的容器，例如多个相似的抽屉，那么描述中应当借助画面中有唯一性、一般不会转移的物品和方位词来辅助限定容器对象。
  - 如果看不清是什么物品，就描述为“某个物品”。
  - 注意描述人物使用的化学品包装上的文字。如果看不清，则描述化学品的颜色、物质状态，例如“红色粉末”、“无色液体”。
  - 多个人物同时出现时，如果人物动作关系密切，则记录为多人共同参与的事件（person_ids 包含多个人物编号），否则分开记录各自的事件。
- 关于 equipment-only 事件
  - 每个能显示数值的设备都应当被记录，**不论示数是否变化**。
  - 如果人物操作的设备有示数，那么该示数及其变化应当记录在这个人的 person 事件中。
  - 如果设备示数与人物动作无关，那么单独记录为 equipment-only 事件（person_ids 为空数组）。
- 关于 none 事件
  - 如果画面中既没有人物活动，也没有设备显示数值或者看不清示数，那么返回 none 事件（person_ids 为空数组，equipment 为空字符串）。
- 外貌描述要从头到脚详细描述，常见特点和稀有特点都要描述。看不清的特征不要描述。
"""
    }
    
    /**
     * 理解视频文件（流式输出）
     * @param videoFile 视频文件
     * @param prompt 提示词
     * @param onProgress 进度回调（接收流式文本）
     * @param onComplete 完成回调（接收完整结果）
     * @param onError 错误回调
     */
    fun understandVideo(
        videoFile: File,
        prompt: String = DEFAULT_PROMPT,
        onProgress: (String) -> Unit,
        onComplete: (UnderstandingResult) -> Unit,
        onError: (Exception) -> Unit
    ) {
        Thread {
            try {
                // 读取视频文件并转为 Base64
                val videoBytes = videoFile.readBytes()
                val videoBase64 = Base64.encodeToString(videoBytes, Base64.NO_WRAP)
                
                Log.d(TAG, "Video size: ${videoBytes.size} bytes, base64 size: ${videoBase64.length}")
                
                // 构建请求体
                val requestBody = buildRequestBody(videoBase64, prompt)
                
                // 发送请求
                val request = Request.Builder()
                    .url(API_URL)
                    .header("Authorization", "Bearer $apiKey")
                    .header("Content-Type", "application/json")
                    .header("Accept", "text/event-stream")
                    .header("X-DashScope-SSE", "enable")
                    .post(requestBody)
                    .build()
                
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    val errorBody = response.body?.string() ?: "Unknown error"
                    throw IOException("API call failed: ${response.code}, $errorBody")
                }
                
                // 处理 SSE 流式响应
                val fullText = StringBuilder()
                response.body?.byteStream()?.bufferedReader()?.use { reader ->
                    processSSEStream(reader, onProgress, fullText)
                }
                
                // 解析完整结果
                val result = parseResult(fullText.toString(), prompt, videoFile.name)
                onComplete(result)
                
            } catch (e: Exception) {
                Log.e(TAG, "Video understanding failed", e)
                onError(e)
            }
        }.start()
    }
    
    /**
     * 构建请求体
     */
    private fun buildRequestBody(videoBase64: String, prompt: String): RequestBody {
        val json = JsonObject().apply {
            addProperty("model", model)
            add("input", JsonObject().apply {
                add("messages", gson.toJsonTree(listOf(
                    mapOf(
                        "role" to "user",
                        "content" to listOf(
                            mapOf(
                                "video" to "data:video/mp4;base64,$videoBase64",
                                "video_fps" to videoFps
                            ),
                            mapOf(
                                "text" to prompt
                            )
                        )
                    )
                )))
            })
            add("parameters", JsonObject().apply {
                addProperty("incremental_output", true)
                addProperty("result_format", "message")
                
                // 添加视频理解参数
                if (enableThinking) {
                    addProperty("enable_thinking", true)
                    addProperty("thinking_budget", thinkingBudget)
                }
                
                if (highResolutionImages) {
                    addProperty("vl_high_resolution_images", true)
                }
                
                addProperty("temperature", temperature)
                addProperty("top_p", topP)
            })
        }
        
        val jsonString = gson.toJson(json)
        Log.d(TAG, "Request body size: ${jsonString.length} bytes")
        
        return jsonString.toRequestBody("application/json; charset=utf-8".toMediaType())
    }
    
    /**
     * 处理 SSE 流式响应
     */
    private fun processSSEStream(
        reader: BufferedReader,
        onProgress: (String) -> Unit,
        fullText: StringBuilder
    ) {
        var line: String?
        while (reader.readLine().also { line = it } != null) {
            val currentLine = line ?: continue
            
            // SSE 格式：data: {...}
            if (currentLine.startsWith("data:")) {
                val jsonData = currentLine.substring(5).trim()
                
                // 检查结束标记
                if (jsonData == "[DONE]") {
                    Log.d(TAG, "Stream completed")
                    break
                }
                
                try {
                    val jsonObject = JsonParser.parseString(jsonData).asJsonObject
                    
                    // 提取文本内容
                    val output = jsonObject.getAsJsonObject("output")
                    val choices = output?.getAsJsonArray("choices")
                    if (choices != null && choices.size() > 0) {
                        val message = choices[0].asJsonObject.getAsJsonObject("message")
                        val content = message?.getAsJsonArray("content")
                        if (content != null && content.size() > 0) {
                            val text = content[0].asJsonObject.get("text")?.asString
                            if (text != null && text.isNotEmpty()) {
                                fullText.append(text)
                                onProgress(text)
                            }
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to parse SSE data: $jsonData", e)
                }
            }
        }
    }
    
    /**
     * 解析结果
     */
    private fun parseResult(
        rawResponse: String,
        prompt: String,
        videoName: String
    ): UnderstandingResult {
        val id = "${System.currentTimeMillis()}_${videoName.substringBeforeLast(".")}"
        val timestamp = System.currentTimeMillis()
        
        // 尝试提取 JSON 部分
        val jsonMatch = Regex("""\{[\s\S]*"events"[\s\S]*"appearances"[\s\S]*\}""").find(rawResponse)
        
        return if (jsonMatch != null) {
            val jsonStr = jsonMatch.value
            try {
                val jsonObject = JsonParser.parseString(jsonStr).asJsonObject
                
                // 解析事件
                val events = mutableListOf<Event>()
                val eventsArray = jsonObject.getAsJsonArray("events")
                if (eventsArray != null) {
                    for (eventElement in eventsArray) {
                        val eventObj = eventElement.asJsonObject
                        val event = Event(
                            eventId = eventObj.get("event_id")?.asString ?: "",
                            startTime = eventObj.get("start_time")?.asString ?: "",
                            endTime = eventObj.get("end_time")?.asString ?: "",
                            eventType = eventObj.get("event_type")?.asString ?: "",
                            personIds = eventObj.getAsJsonArray("person_ids")?.map { it.asString } ?: emptyList(),
                            equipment = eventObj.get("equipment")?.asString ?: "",
                            description = eventObj.get("description")?.asString ?: ""
                        )
                        events.add(event)
                    }
                }
                
                // 解析人物外貌
                val appearances = mutableListOf<Appearance>()
                val appearancesArray = jsonObject.getAsJsonArray("appearances")
                if (appearancesArray != null) {
                    for (appearanceElement in appearancesArray) {
                        val appearanceObj = appearanceElement.asJsonObject
                        val appearance = Appearance(
                            personId = appearanceObj.get("person_id")?.asString ?: "",
                            features = appearanceObj.get("features")?.asString ?: ""
                        )
                        appearances.add(appearance)
                    }
                }
                
                UnderstandingResult(
                    id = id,
                    timestamp = timestamp,
                    prompt = prompt,
                    events = events,
                    appearances = appearances,
                    rawResponse = rawResponse,
                    isStreaming = false,
                    parseError = null  // 解析成功
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse JSON", e)
                // 解析失败，返回错误信息
                UnderstandingResult(
                    id = id,
                    timestamp = timestamp,
                    prompt = prompt,
                    events = emptyList(),
                    appearances = emptyList(),
                    rawResponse = rawResponse,
                    isStreaming = false,
                    parseError = "不符合预期的JSON格式"  // 友好的错误信息
                )
            }
        } else {
            // 未找到 JSON，返回错误信息
            Log.w(TAG, "No JSON found in response")
            UnderstandingResult(
                id = id,
                timestamp = timestamp,
                prompt = prompt,
                events = emptyList(),
                appearances = emptyList(),
                rawResponse = rawResponse,
                isStreaming = false,
                parseError = "响应中未找到JSON格式数据"
            )
        }
    }
}

