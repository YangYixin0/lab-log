package com.example.lablogcamera.viewmodel

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.lablogcamera.data.RecordingItem
import com.example.lablogcamera.data.UnderstandingResult
import com.example.lablogcamera.service.VideoUnderstandingService
import com.example.lablogcamera.storage.StorageManager
import com.example.lablogcamera.utils.ConfigManager
import com.example.lablogcamera.utils.UsageCounter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File

private const val TAG = "DetailViewModel"

/**
 * 详情页 ViewModel
 */
class DetailViewModel(application: Application) : AndroidViewModel(application) {
    private val storageManager = StorageManager(application)
    
    private val _recording = MutableStateFlow<RecordingItem?>(null)
    val recording: StateFlow<RecordingItem?> = _recording.asStateFlow()
    
    private val _isUnderstanding = MutableStateFlow(false)
    val isUnderstanding: StateFlow<Boolean> = _isUnderstanding.asStateFlow()
    
    private val _streamingText = MutableStateFlow("")
    val streamingText: StateFlow<String> = _streamingText.asStateFlow()
    
    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()
    
    private val _usageCount = MutableStateFlow(0)
    val usageCount: StateFlow<Int> = _usageCount.asStateFlow()
    
    private val _canUse = MutableStateFlow(true)
    val canUse: StateFlow<Boolean> = _canUse.asStateFlow()
    
    init {
        ConfigManager.initialize(application)
        updateUsageCount()
    }
    
    /**
     * 加载录制记录
     */
    fun loadRecording(id: String) {
        viewModelScope.launch(Dispatchers.IO) {
            val recording = storageManager.getRecording(id)
            _recording.value = recording
            if (recording == null) {
                _errorMessage.value = "录制记录不存在"
            }
        }
    }
    
    /**
     * 开始理解视频
     */
    fun startUnderstanding(prompt: String, model: String = ConfigManager.qwenModel) {
        val recording = _recording.value
        if (recording == null) {
            _errorMessage.value = "录制记录不存在"
            return
        }
        
        // 检查使用次数
        if (!UsageCounter.canUse(getApplication(), ConfigManager.maxApiCalls)) {
            _errorMessage.value = "已达到使用次数限制（${ConfigManager.maxApiCalls}次）"
            _canUse.value = false
            return
        }
        
        viewModelScope.launch(Dispatchers.IO) {
            _isUnderstanding.value = true
            _streamingText.value = ""
            _errorMessage.value = null
            
            try {
                val videoFile = File(recording.videoPath)
                if (!videoFile.exists()) {
                    _errorMessage.value = "视频文件不存在"
                    _isUnderstanding.value = false
                    return@launch
                }
                
                // 根据模型选择 API Key
                val apiKey = if (model.contains("google/")) {
                    ConfigManager.openRouterApiKey
                } else {
                    ConfigManager.apiKey
                }
                
                if (apiKey.isEmpty() || apiKey == "your_api_key_here") {
                    _errorMessage.value = "请先在 assets/config.properties 中配置 API Key"
                    _isUnderstanding.value = false
                    return@launch
                }
                
                // 根据选择的模型创建服务实例
                val videoUnderstandingService = VideoUnderstandingService(
                    apiKey = apiKey,
                    model = model,
                    timeoutMs = ConfigManager.apiTimeoutMs,
                    videoFps = ConfigManager.videoFpsForApi,
                    enableThinking = ConfigManager.enableThinking,
                    thinkingBudget = ConfigManager.thinkingBudget,
                    highResolutionImages = ConfigManager.vlHighResolutionImages,
                    temperature = ConfigManager.vlTemperature,
                    topP = ConfigManager.vlTopP
                )
                
                videoUnderstandingService.understandVideo(
                    videoFile = videoFile,
                    prompt = prompt,
                    onProgress = { text ->
                        _streamingText.value += text
                    },
                    onComplete = { result ->
                        // 成功后增加使用次数
                        UsageCounter.incrementAndCheck(getApplication(), ConfigManager.maxApiCalls)
                        updateUsageCount()

                        // 保存结果
                        val updatedResults = recording.results + result
                        storageManager.saveResults(recording.id, updatedResults)
                        
                        // 重新加载录制记录
                        loadRecording(recording.id)
                        
                        _isUnderstanding.value = false
                        _streamingText.value = ""
                        
                        Log.d(TAG, "Understanding completed: ${result.events.size} events, ${result.appearances.size} appearances")
                    },
                    onError = { error ->
                        val currentRecording = _recording.value
                        if (currentRecording != null && error.message?.contains("不占用限额") == true) {
                            // 针对特定的云服务不稳定错误，记录一个带错误信息的结果
                            val failedResult = UnderstandingResult(
                                id = "${System.currentTimeMillis()}_failed",
                                timestamp = System.currentTimeMillis(),
                                prompt = prompt,
                                events = emptyList(),
                                appearances = emptyList(),
                                rawResponse = error.message ?: "Unknown error",
                                model = model,
                                isStreaming = false,
                                parseError = error.message
                            )
                            val updatedResults = currentRecording.results + failedResult
                            storageManager.saveResults(currentRecording.id, updatedResults)
                            loadRecording(currentRecording.id)
                        } else {
                            _errorMessage.value = "理解失败: ${error.message}"
                        }
                        
                        _isUnderstanding.value = false
                        _streamingText.value = ""
                        Log.e(TAG, "Understanding failed", error)
                    }
                )
            } catch (e: Exception) {
                _errorMessage.value = "理解失败: ${e.message}"
                _isUnderstanding.value = false
                _streamingText.value = ""
                Log.e(TAG, "Understanding failed", e)
            }
        }
    }
    
    /**
     * 删除理解结果
     */
    fun deleteResult(resultId: String) {
        val recording = _recording.value ?: return
        
        viewModelScope.launch(Dispatchers.IO) {
            val updatedResults = recording.results.filter { it.id != resultId }
            storageManager.saveResults(recording.id, updatedResults)
            loadRecording(recording.id)
        }
    }
    
    /**
     * 清除错误消息
     */
    fun clearError() {
        _errorMessage.value = null
    }
    
    /**
     * 更新使用次数
     */
    private fun updateUsageCount() {
        _usageCount.value = UsageCounter.getCount(getApplication())
        _canUse.value = UsageCounter.canUse(getApplication(), ConfigManager.maxApiCalls)
    }
}


