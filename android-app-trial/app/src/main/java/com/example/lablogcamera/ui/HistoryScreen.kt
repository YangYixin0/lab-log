package com.example.lablogcamera.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.lablogcamera.data.RecordingItem
import com.example.lablogcamera.viewmodel.HistoryViewModel
import java.io.File
import java.text.SimpleDateFormat
import java.util.*

/**
 * 历史记录界面
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(
    viewModel: HistoryViewModel = viewModel(),
    onNavigateToDetail: (String) -> Unit
) {
    val recordings by viewModel.recordings.collectAsState()
    val isLoading by viewModel.isLoading.collectAsState()
    
    Scaffold(
        floatingActionButton = {
            FloatingActionButton(
                onClick = { viewModel.loadRecordings() }
            ) {
                Icon(Icons.Default.Refresh, contentDescription = "刷新")
            }
        }
    ) { paddingValues ->
        if (isLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        } else if (recordings.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "暂无录制记录",
                    style = MaterialTheme.typography.bodyLarge
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(recordings) { recording ->
                    RecordingCard(
                        recording = recording,
                        onClick = { onNavigateToDetail(recording.id) }
                    )
                }
            }
        }
    }
}

/**
 * 录制卡片
 */
@Composable
fun RecordingCard(
    recording: RecordingItem,
    onClick: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // 缩略图
            if (recording.thumbnailPath != null && File(recording.thumbnailPath).exists()) {
                val bitmap = remember(recording.thumbnailPath) {
                    BitmapFactory.decodeFile(recording.thumbnailPath)
                }
                if (bitmap != null) {
                    Image(
                        bitmap = bitmap.asImageBitmap(),
                        contentDescription = "缩略图",
                        modifier = Modifier
                            .size(80.dp)
                            .aspectRatio(1f),
                        contentScale = ContentScale.Crop
                    )
                } else {
                    PlaceholderThumbnail()
                }
            } else {
                PlaceholderThumbnail()
            }
            
            // 信息
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                // 时间戳
                Text(
                    text = formatTimestamp(recording.createdAt),
                    style = MaterialTheme.typography.titleMedium
                )
                
                // 时长
                Text(
                    text = "时长: ${formatDuration(recording.duration)}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                
                // 分辨率和编码
                Text(
                    text = "${recording.resolution} · ${recording.codec}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                
                // 理解结果数量
                if (recording.results.isNotEmpty()) {
                    Text(
                        text = "已理解 ${recording.results.size} 次",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
            }
        }
    }
}

/**
 * 占位缩略图
 */
@Composable
fun PlaceholderThumbnail() {
    Box(
        modifier = Modifier
            .size(80.dp)
            .aspectRatio(1f),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = "无缩略图",
            style = MaterialTheme.typography.bodySmall
        )
    }
}

/**
 * 格式化时间戳
 */
private fun formatTimestamp(timestamp: Long): String {
    val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault())
    return sdf.format(Date(timestamp))
}

/**
 * 格式化时长（毫秒 -> mm:ss）
 */
private fun formatDuration(durationMs: Long): String {
    val seconds = (durationMs / 1000).toInt()
    val minutes = seconds / 60
    val secs = seconds % 60
    return "%02d:%02d".format(minutes, secs)
}

