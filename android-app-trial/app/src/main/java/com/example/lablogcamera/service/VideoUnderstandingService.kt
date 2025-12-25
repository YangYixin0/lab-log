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
    private val timeoutMs: Long = 120000L
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

要求：
1. 输出完整的事件表（events数组），每个事件包含：
   - event_id: 事件编号（evt_00001、evt_00002...）
   - start_time: 开始时间（从视频水印读取，格式hh:mm:ss）
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
}"""
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
                                "video" to "data:video/mp4;base64,$videoBase64"
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
                    isStreaming = false
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse JSON", e)
                // 解析失败，返回原始响应
                UnderstandingResult(
                    id = id,
                    timestamp = timestamp,
                    prompt = prompt,
                    events = emptyList(),
                    appearances = emptyList(),
                    rawResponse = rawResponse,
                    isStreaming = false
                )
            }
        } else {
            // 未找到 JSON，返回原始响应
            Log.w(TAG, "No JSON found in response")
            UnderstandingResult(
                id = id,
                timestamp = timestamp,
                prompt = prompt,
                events = emptyList(),
                appearances = emptyList(),
                rawResponse = rawResponse,
                isStreaming = false
            )
        }
    }
}

