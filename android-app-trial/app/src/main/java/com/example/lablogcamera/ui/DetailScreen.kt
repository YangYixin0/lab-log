package com.example.lablogcamera.ui

import android.net.Uri
import android.widget.MediaController
import android.widget.VideoView
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.lablogcamera.data.CsvExporter
import com.example.lablogcamera.data.Event
import com.example.lablogcamera.data.Appearance
import com.example.lablogcamera.data.UnderstandingResult
import com.example.lablogcamera.service.VideoUnderstandingService
import com.example.lablogcamera.utils.ConfigManager
import com.example.lablogcamera.viewmodel.DetailViewModel

/**
 * 详情页
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(
    videoId: String,
    viewModel: DetailViewModel = viewModel(),
    onNavigateBack: () -> Unit
) {
    val clipboardManager = LocalClipboardManager.current
    val context = LocalContext.current
    
    val recording by viewModel.recording.collectAsState()
    val isUnderstanding by viewModel.isUnderstanding.collectAsState()
    val streamingText by viewModel.streamingText.collectAsState()
    val errorMessage by viewModel.errorMessage.collectAsState()
    val usageCount by viewModel.usageCount.collectAsState()
    val canUse by viewModel.canUse.collectAsState()
    
    // 重新理解相关状态
    var showReunderstandDialog by remember { mutableStateOf(false) }
    var reunderstandPrompt by remember { mutableStateOf(VideoUnderstandingService.DEFAULT_PROMPT) }
    var selectedModel by remember { mutableStateOf(ConfigManager.qwenModel) }
    
    // 加载录制记录
    LaunchedEffect(videoId) {
        viewModel.loadRecording(videoId)
    }
    
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("录制详情") },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    Text(
                        text = "已理解 $usageCount / ${ConfigManager.maxApiCalls} 次",
                        modifier = Modifier.padding(end = 16.dp)
                    )
                },
                windowInsets = WindowInsets(0, 0, 0, 0)  // 移除所有默认内边距
            )
        }
    ) { paddingValues ->
        if (recording == null) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                contentAlignment = Alignment.Center
            ) {
                if (errorMessage != null) {
                    Text(errorMessage!!)
                } else {
                    CircularProgressIndicator()
                }
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                // 视频播放器
                VideoPlayer(videoPath = recording!!.videoPath)
                
                // 视频信息
                VideoInfoCard(
                    resolution = recording!!.resolution,
                    fps = recording!!.fps,
                    bitrate = recording!!.bitrate,
                    codec = recording!!.codec
                )
                
                // 理解结果列表
                recording!!.results.forEach { result ->
                    UnderstandingResultCard(
                        result = result,
                        clipboardManager = clipboardManager
                    )
                }
                
                // 正在理解中的结果
                if (isUnderstanding) {
                    StreamingResultCard(
                        streamingText = streamingText
                    )
                }
                
                // 理解按钮（根据是否有理解结果显示不同文本）
                val hasResults = recording!!.results.isNotEmpty()
                Button(
                    onClick = { showReunderstandDialog = true },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isUnderstanding && canUse
                ) {
                    Text(
                        when {
                            !canUse -> "已达使用限制"
                            hasResults -> "再次理解"
                            else -> "开始理解"
                        }
                    )
                }
                
                // 错误消息
                if (errorMessage != null) {
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.errorContainer
                        )
                    ) {
                        Row(
                            modifier = Modifier.padding(16.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = errorMessage!!,
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                modifier = Modifier.weight(1f)
                            )
                            TextButton(onClick = { viewModel.clearError() }) {
                                Text("关闭")
                            }
                        }
                    }
                }
            }
        }
    }
    
    // 重新理解对话框
    if (showReunderstandDialog) {
        AlertDialog(
            onDismissRequest = { showReunderstandDialog = false },
            title = { 
                Text(
                    text = "视频理解参数",
                    style = MaterialTheme.typography.titleLarge
                ) 
            },
            text = {
                Box(
                    modifier = Modifier
                        .width(500.dp)  // 固定宽度，更宽
                        .heightIn(max = 600.dp)  // 最大高度，更高
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(8.dp)  // 减少间距：12dp -> 8dp
                    ) {
                        // 模型选择
                        Text(
                            text = "模型:",
                            style = MaterialTheme.typography.bodyMedium,  // 改小：bodyLarge -> bodyMedium
                            fontWeight = FontWeight.Medium
                        )
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {  // 减少间距：4dp -> 2dp
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                RadioButton(
                                    selected = selectedModel == "qwen3-vl-flash",
                                    onClick = { selectedModel = "qwen3-vl-flash" }
                                )
                                Text(
                                    text = "qwen3-vl-flash",
                                    style = MaterialTheme.typography.bodyMedium,  // 统一字体大小
                                    modifier = Modifier.padding(start = 4.dp)  // 减少间距：8dp -> 4dp
                                )
                            }
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                RadioButton(
                                    selected = selectedModel == "qwen3-vl-plus",
                                    onClick = { selectedModel = "qwen3-vl-plus" }
                                )
                                Text(
                                    text = "qwen3-vl-plus",
                                    style = MaterialTheme.typography.bodyMedium,  // 统一字体大小
                                    modifier = Modifier.padding(start = 4.dp)  // 减少间距：8dp -> 4dp
                                )
                            }
                        }
                        
                        Spacer(modifier = Modifier.height(2.dp))  // 减少间距：4dp -> 2dp
                        
                        // 提示词输入
                        Text(
                            text = "提示词:",
                            style = MaterialTheme.typography.bodyMedium,  // 改小：bodyLarge -> bodyMedium
                            fontWeight = FontWeight.Medium
                        )
                        OutlinedTextField(
                            value = reunderstandPrompt,
                            onValueChange = { reunderstandPrompt = it },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(400.dp),  // 固定高度，更高：200dp -> 400dp
                            textStyle = MaterialTheme.typography.bodySmall,  // 文本字体改小
                            maxLines = Int.MAX_VALUE  // 不限制行数
                        )
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        viewModel.startUnderstanding(reunderstandPrompt, selectedModel)
                        showReunderstandDialog = false
                    }
                ) {
                    Text("确定")
                }
            },
            dismissButton = {
                TextButton(onClick = { showReunderstandDialog = false }) {
                    Text("取消")
                }
            },
            properties = androidx.compose.ui.window.DialogProperties(
                usePlatformDefaultWidth = false  // 不使用默认宽度限制
            )
        )
    }
}

/**
 * 视频播放器
 */
@Composable
fun VideoPlayer(videoPath: String) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
    ) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { context ->
                VideoView(context).apply {
                    // 添加播放控制器
                    val mediaController = MediaController(context)
                    mediaController.setAnchorView(this)
                    setMediaController(mediaController)
                    
                    // 使用文件 URI
                    setVideoURI(Uri.parse("file://$videoPath"))
                    setOnPreparedListener { mediaPlayer ->
                        mediaPlayer.isLooping = true
                    }
                    start()
                }
            }
        )
    }
}

/**
 * 视频信息卡片（可折叠）
 */
@Composable
fun VideoInfoCard(
    resolution: String,
    fps: Float,
    bitrate: Float,
    codec: String
) {
    var expanded by remember { mutableStateOf(false) }
    
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            // 标题行（带折叠按钮）
            Row(
                modifier = Modifier
                    .fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "视频信息",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                IconButton(onClick = { expanded = !expanded }) {
                    Icon(
                        imageVector = if (expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                        contentDescription = if (expanded) "收起" else "展开"
                    )
                }
            }
            
            // 可折叠内容
            AnimatedVisibility(visible = expanded) {
                Column(
                    modifier = Modifier.padding(top = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Text("分辨率: $resolution")
                    Text("帧率: %.1f fps".format(fps))
                    Text("码率: %.2f Mbps".format(bitrate))
                    Text("编码: $codec")
                }
            }
        }
    }
}

/**
 * 理解结果卡片
 */
@Composable
fun UnderstandingResultCard(
    result: UnderstandingResult,
    clipboardManager: androidx.compose.ui.platform.ClipboardManager
) {
    var expanded by remember { mutableStateOf(true) }
    var showJson by remember { mutableStateOf(true) }  // 默认显示 JSON
    
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            // 标题行
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "理解结果",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // JSON/表格切换按钮
                    TextButton(onClick = { showJson = !showJson }) {
                        Text(if (showJson) "查看表格" else "查看JSON")
                    }
                    IconButton(onClick = { expanded = !expanded }) {
                        Icon(
                            if (expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                            contentDescription = if (expanded) "折叠" else "展开"
                        )
                    }
                }
            }
            
            AnimatedVisibility(visible = expanded) {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Divider()
                    
                    // 如果有解析错误，显示错误信息
                    if (result.parseError != null) {
                        Card(
                            modifier = Modifier.fillMaxWidth(),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.errorContainer
                            )
                        ) {
                            Text(
                                text = "⚠️ ${result.parseError}",
                                modifier = Modifier.padding(16.dp),
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                    
                    if (showJson) {
                        // JSON 原文显示
                        JsonSection(
                            json = result.rawResponse,
                            onCopy = {
                                clipboardManager.setText(AnnotatedString(result.rawResponse))
                            }
                        )
                    } else {
                        // 事件表
                        EventTable(
                            events = result.events,
                            onCopy = {
                                val csv = CsvExporter.eventsToCSV(result.events)
                                clipboardManager.setText(AnnotatedString(csv))
                            }
                        )
                        
                        // 人物外貌表
                        AppearanceTable(
                            appearances = result.appearances,
                            onCopy = {
                                val csv = CsvExporter.appearancesToCSV(result.appearances)
                                clipboardManager.setText(AnnotatedString(csv))
                            }
                        )
                    }
                    
                    // 提示词（始终显示）
                    PromptSection(
                        prompt = result.prompt,
                        onCopy = {
                            clipboardManager.setText(AnnotatedString(result.prompt))
                        }
                    )
                }
            }
        }
    }
}

/**
 * 事件表
 */
@Composable
fun EventTable(
    events: List<Event>,
    onCopy: () -> Unit
) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "事件表 (${events.size})",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold
            )
            TextButton(onClick = onCopy) {
                Text("复制CSV")
            }
        }
        
        if (events.isEmpty()) {
            Text("无事件", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            events.forEach { event ->
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            text = "${event.startTime} - ${event.endTime}",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold
                        )
                        Text("类型: ${event.eventType}")
                        Text("人物: ${event.personIds.joinToString(", ")}")
                        Text("设备: ${event.equipment}")
                        Text("描述: ${event.description}")
                    }
                }
            }
        }
    }
}

/**
 * 人物外貌表
 */
@Composable
fun AppearanceTable(
    appearances: List<Appearance>,
    onCopy: () -> Unit
) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "人物外貌表 (${appearances.size})",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold
            )
            TextButton(onClick = onCopy) {
                Text("复制CSV")
            }
        }
        
        if (appearances.isEmpty()) {
            Text("无人物", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            appearances.forEach { appearance ->
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            text = appearance.personId,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Bold
                        )
                        Text(appearance.features)
                    }
                }
            }
        }
    }
}

/**
 * 提示词部分
 */
@Composable
fun PromptSection(
    prompt: String,
    onCopy: () -> Unit
) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "所用提示词",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold
            )
            TextButton(onClick = onCopy) {
                Text("复制")
            }
        }
        
        Text(
            text = prompt,
            modifier = Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .padding(12.dp),
            style = MaterialTheme.typography.bodySmall
        )
    }
}

/**
 * 流式输出结果卡片
 */
@Composable
fun StreamingResultCard(streamingText: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                CircularProgressIndicator(modifier = Modifier.size(24.dp))
                Text(
                    text = "正在理解...",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
            }
            
            if (streamingText.isNotEmpty()) {
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = streamingText,
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surface)
                        .padding(12.dp),
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }
    }
}

/**
 * JSON 原文显示区域
 */
@Composable
fun JsonSection(
    json: String,
    onCopy: () -> Unit
) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "JSON 原文",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold
            )
            TextButton(onClick = onCopy) {
                Text("复制")
            }
        }
        
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant
            )
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 400.dp)  // 限制最大高度
                    .verticalScroll(rememberScrollState())
                    .padding(12.dp)
            ) {
                Text(
                    text = json.ifEmpty { "暂无数据" },
                    style = MaterialTheme.typography.bodySmall.copy(
                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

