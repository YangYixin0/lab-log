package com.example.lablogcamera.ui

import android.hardware.camera2.CameraCharacteristics
import android.util.Log
import android.view.OrientationEventListener
import androidx.camera.core.CameraSelector
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.lablogcamera.service.VideoUnderstandingService
import com.example.lablogcamera.viewmodel.RecordingState
import com.example.lablogcamera.viewmodel.RecordingViewModel

private const val TAG = "RecordingScreen"

/**
 * 录制界面
 */
@Composable
fun RecordingScreen(
    viewModel: RecordingViewModel = viewModel(),
    onNavigateToDetail: (String) -> Unit
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val clipboardManager = LocalClipboardManager.current
    
    val recordingState by viewModel.recordingState.collectAsState()
    val recordingDuration by viewModel.recordingDuration.collectAsState()
    val currentFps by viewModel.currentFps.collectAsState()
    val prompt by viewModel.prompt.collectAsState()
    val errorMessage by viewModel.errorMessage.collectAsState()
    val completedVideoId by viewModel.completedVideoId.collectAsState()
    
    // 监听设备物理方向变化
    DisposableEffect(context) {
        val orientationListener = object : OrientationEventListener(context) {
            override fun onOrientationChanged(orientation: Int) {
                if (orientation == ORIENTATION_UNKNOWN) return
                // 将连续的方向角度转换为离散的旋转角度
                val rotation = when {
                    orientation >= 315 || orientation < 45 -> 0      // 竖向（正常）
                    orientation >= 45 && orientation < 135 -> 90     // 右横向
                    orientation >= 135 && orientation < 225 -> 180   // 倒置
                    orientation >= 225 && orientation < 315 -> 270   // 左横向
                    else -> 0
                }
                // 更新 ViewModel 中的物理方向状态
                viewModel.updateDevicePhysicalRotation(rotation)
            }
        }
        if (orientationListener.canDetectOrientation()) {
            orientationListener.enable()
        }
        onDispose { 
            orientationListener.disable() 
        }
    }
    
    // 创建 ImageAnalysis
    LaunchedEffect(Unit) {
        viewModel.createImageAnalysis()
    }
    
    // 录制完成后，自动跳转到详情页（只跳转一次）
    LaunchedEffect(completedVideoId) {
        if (completedVideoId != null) {
            onNavigateToDetail(completedVideoId!!)
            // 清除状态，避免返回后再次跳转
            viewModel.clearCompletedVideo()
        }
    }
    
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        // 相机预览区域（宽高比2:1，高度约为屏幕宽度的一半）
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(2f)
                .background(Color.Black)
        ) {
            // 相机预览
            CameraPreview(
                viewModel = viewModel,
                lifecycleOwner = lifecycleOwner
            )
            
            // 录制状态显示
            if (recordingState == RecordingState.RECORDING) {
                Column(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(16.dp)
                ) {
                    // 帧率显示
                    Text(
                        text = "FPS: %.1f".format(currentFps),
                        color = Color.White,
                        fontSize = 16.sp,
                        modifier = Modifier
                            .background(Color.Black.copy(alpha = 0.6f))
                            .padding(horizontal = 8.dp, vertical = 4.dp)
                    )
                }
                
                // 录制指示（红点）
                Box(
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(16.dp)
                        .size(16.dp)
                        .background(Color.Red, shape = MaterialTheme.shapes.small)
                )
            }
        }
        
        // 控制区域
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .background(MaterialTheme.colorScheme.surface)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // 录制时长显示
            Text(
                text = formatDuration(recordingDuration),
                style = MaterialTheme.typography.headlineMedium
            )
            
            // 开始/停止按钮
            when (recordingState) {
                RecordingState.IDLE -> {
                    Button(
                        onClick = { viewModel.startRecording() },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("开始录制")
                    }
                }
                RecordingState.RECORDING -> {
                    Button(
                        onClick = { viewModel.stopRecording() },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.error
                        )
                    ) {
                        Text("停止录制")
                    }
                }
                RecordingState.COMPLETED -> {
                    Button(
                        onClick = { viewModel.resetRecording() },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("重新录制")
                    }
                }
            }
            
            // 提示词区域
            Text(
                text = "提示词",
                style = MaterialTheme.typography.titleMedium
            )
            
            OutlinedTextField(
                value = prompt,
                onValueChange = { viewModel.updatePrompt(it) },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 200.dp),
                enabled = recordingState == RecordingState.IDLE,
                maxLines = 10
            )
            
            // 提示词操作按钮
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                OutlinedButton(
                    onClick = { viewModel.resetPrompt() },
                    modifier = Modifier.weight(1f),
                    enabled = recordingState == RecordingState.IDLE
                ) {
                    Text("重置")
                }
                
                OutlinedButton(
                    onClick = {
                        clipboardManager.setText(AnnotatedString(prompt))
                    },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("复制")
                }
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

/**
 * 相机预览
 */
@Composable
fun CameraPreview(
    viewModel: RecordingViewModel,
    lifecycleOwner: androidx.lifecycle.LifecycleOwner
) {
    val context = LocalContext.current
    val imageAnalysis by viewModel.imageAnalysis
    
    val previewView = remember {
        PreviewView(context).apply {
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
            scaleType = PreviewView.ScaleType.FIT_CENTER
        }
    }
    
    // 绑定相机
    LaunchedEffect(imageAnalysis) {
        try {
            val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
            val cameraProvider = cameraProviderFuture.get()
            cameraProvider.unbindAll()
            
            // 固定使用后置摄像头
            val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA
            
            // 创建预览
            val preview = Preview.Builder()
                .build()
                .also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }
            
            // 绑定相机
            if (imageAnalysis != null) {
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    cameraSelector,
                    preview,
                    imageAnalysis
                )
                Log.d(TAG, "Camera bound with ImageAnalysis")
            } else {
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    cameraSelector,
                    preview
                )
                Log.d(TAG, "Camera bound without ImageAnalysis")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Camera binding failed", e)
        }
    }
    
    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = { previewView }
    )
}

/**
 * 格式化时长（秒 -> mm:ss）
 */
private fun formatDuration(seconds: Int): String {
    val minutes = seconds / 60
    val secs = seconds % 60
    return "%02d:%02d / 01:00".format(minutes, secs)
}

