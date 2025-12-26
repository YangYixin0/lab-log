package com.example.lablogcamera.ui

import android.hardware.camera2.CameraCharacteristics
import android.util.Log
import android.util.Rational
import android.view.OrientationEventListener
import androidx.camera.core.CameraSelector
import androidx.camera.core.Preview
import androidx.camera.core.UseCaseGroup
import androidx.camera.core.ViewPort
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
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
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
    
    val recordingState by viewModel.recordingState.collectAsState()
    val recordingDuration by viewModel.recordingDuration.collectAsState()
    val currentFps by viewModel.currentFps.collectAsState()
    val errorMessage by viewModel.errorMessage.collectAsState()
    val completedVideoId by viewModel.completedVideoId.collectAsState()
    val analysisResolution by viewModel.analysisResolution.collectAsState()
    
    // 显示旋转状态（由 CameraPreview 更新）
    var displayRotation by remember { mutableStateOf(android.view.Surface.ROTATION_0) }
    
    // 标记是否需要在重置后自动开始录制
    var shouldStartAfterReset by remember { mutableStateOf(false) }
    
    // 计算预览宽高比（基于实际的 ImageAnalysis 分辨率和显示方向）
    // 注意：预览容器的宽高比应该基于显示旋转，而不是设备物理方向
    // 传感器输出通常是横向的（960x720），当显示旋转为90/270度时，需要交换宽高比
    val previewAspectRatio = remember(analysisResolution, displayRotation) {
        analysisResolution?.let { (width, height) ->
            // 如果显示旋转是90或270度，预览容器需要交换宽高比
            // 因为传感器输出是横向的（960x720），但显示时需要竖向（720x960）
            if (displayRotation == android.view.Surface.ROTATION_90 || displayRotation == android.view.Surface.ROTATION_270) {
                height.toFloat() / width.toFloat()
            } else {
                width.toFloat() / height.toFloat()
            }
        } ?: 1f  // 默认 1:1
    }
    
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
    
    // 监听状态变化：当从 COMPLETED 变为 IDLE 且需要自动开始时，自动开始录制
    LaunchedEffect(recordingState, shouldStartAfterReset) {
        if (recordingState == RecordingState.IDLE && shouldStartAfterReset) {
            shouldStartAfterReset = false
            viewModel.startRecording()
        }
    }
    
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        // 相机预览区域（动态宽高比，匹配实际的 ImageAnalysis 分辨率）
        Box(
            modifier = Modifier
                .fillMaxWidth(0.75f)  // 限制宽度为屏幕的75%
                .align(Alignment.CenterHorizontally)  // 水平居中
                .aspectRatio(previewAspectRatio)
                .background(Color.Black)
        ) {
            // 相机预览
            CameraPreview(
                viewModel = viewModel,
                lifecycleOwner = lifecycleOwner,
                analysisResolution = analysisResolution,
                onDisplayRotationChanged = { rotation -> displayRotation = rotation }
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
                        onClick = { 
                            shouldStartAfterReset = true
                            viewModel.resetRecording()
                        },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("开始录制")
                    }
                }
            }
            
            // 错误消息（放在提示词上方）
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
    lifecycleOwner: androidx.lifecycle.LifecycleOwner,
    analysisResolution: Pair<Int, Int>?,
    onDisplayRotationChanged: (Int) -> Unit
) {
    val context = LocalContext.current
    val imageAnalysis by viewModel.imageAnalysis
    
    val previewView = remember {
        PreviewView(context).apply {
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
            scaleType = PreviewView.ScaleType.FILL_CENTER  // 填充容器，裁剪多余部分
        }
    }
    
    // 每次重组时检查显示旋转变化，并通知父组件
    SideEffect {
        val rotation = previewView.display?.rotation ?: android.view.Surface.ROTATION_0
        onDisplayRotationChanged(rotation)
    }
    
    // 绑定相机（监听 imageAnalysis 和 analysisResolution 的变化）
    LaunchedEffect(imageAnalysis, analysisResolution) {
        try {
            val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
            val cameraProvider = cameraProviderFuture.get()
            cameraProvider.unbindAll()
            
            // 固定使用后置摄像头
            val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA
            
            // 当前显示方向（用于同步 Preview / ImageAnalysis / ViewPort）
            val rotation = previewView.display?.rotation ?: android.view.Surface.ROTATION_0
            onDisplayRotationChanged(rotation)
            
            // 根据显示旋转和 ImageAnalysis 分辨率计算 ViewPort 宽高比
            // 传感器输出通常是横向的（960x720），当显示旋转为90/270度时，需要交换宽高比
            val (w, h) = analysisResolution ?: (960 to 720)
            val rational = if (rotation == android.view.Surface.ROTATION_90 || rotation == android.view.Surface.ROTATION_270) {
                Rational(h, w)  // 显示旋转90/270度时，交换宽高比
            } else {
                Rational(w, h)  // 显示旋转0/180度时，保持原始宽高比
            }
            
            // 创建预览
            val preview = Preview.Builder()
                .setTargetRotation(rotation)
                .build()
                .also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }
            
            // 如果 ImageAnalysis 存在，使用 ViewPort + UseCaseGroup 确保 FOV 一致
            if (imageAnalysis != null && analysisResolution != null) {
                // 根据 ImageAnalysis 的实际分辨率和显示旋转创建动态 ViewPort
                val viewPort = ViewPort.Builder(
                    rational,  // 使用根据显示旋转计算的一致宽高比
                    rotation   // 使用当前显示旋转，避免 FOV 被裁剪
                ).build()
                
                // 同步旋转给 ImageAnalysis
                imageAnalysis?.targetRotation = rotation
                
                // 创建 UseCaseGroup，所有 UseCase 共享同一个 ViewPort
                val useCaseGroup = UseCaseGroup.Builder()
                    .addUseCase(preview)
                    .addUseCase(imageAnalysis!!)
                    .setViewPort(viewPort)
                    .build()
                
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    cameraSelector,
                    useCaseGroup
                )
                Log.d(TAG, "Camera bound with ViewPort(${w}x${h}, rotation=$rotation) + ImageAnalysis")
            } else {
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    cameraSelector,
                    preview
                )
                Log.d(TAG, "Camera bound without ImageAnalysis (imageAnalysis=${imageAnalysis != null}, resolution=$analysisResolution)")
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

