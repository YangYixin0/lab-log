package com.example.lablogcamera.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.lablogcamera.data.RecordingItem
import com.example.lablogcamera.storage.StorageManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * 历史记录 ViewModel
 */
class HistoryViewModel(application: Application) : AndroidViewModel(application) {
    private val storageManager = StorageManager(application)
    
    private val _recordings = MutableStateFlow<List<RecordingItem>>(emptyList())
    val recordings: StateFlow<List<RecordingItem>> = _recordings.asStateFlow()
    
    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()
    
    init {
        loadRecordings()
    }
    
    /**
     * 加载录制列表
     */
    fun loadRecordings() {
        viewModelScope.launch(Dispatchers.IO) {
            _isLoading.value = true
            try {
                val recordings = storageManager.listRecordings()
                _recordings.value = recordings
            } finally {
                _isLoading.value = false
            }
        }
    }
    
    /**
     * 删除录制
     */
    fun deleteRecording(id: String) {
        viewModelScope.launch(Dispatchers.IO) {
            storageManager.deleteRecording(id)
            loadRecordings()
        }
    }
}


