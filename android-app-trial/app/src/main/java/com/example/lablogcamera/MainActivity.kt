package com.example.lablogcamera

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.VideoCall
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.example.lablogcamera.ui.DetailScreen
import com.example.lablogcamera.ui.HistoryScreen
import com.example.lablogcamera.ui.RecordingScreen
import com.example.lablogcamera.ui.theme.LabLogCameraTheme
import com.example.lablogcamera.utils.ConfigManager
import com.example.lablogcamera.utils.UsageCounter
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState

/**
 * Lab Log 试用版 App
 * 主 Activity
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        
        // 初始化配置
        ConfigManager.initialize(this)
        
        setContent {
            LabLogCameraTheme {
                LabLogTrialApp()
            }
        }
    }
}

/**
 * 导航路由
 */
sealed class Screen(val route: String) {
    object Recording : Screen("recording")
    object History : Screen("history")
    object Detail : Screen("detail/{videoId}") {
        fun createRoute(videoId: String) = "detail/$videoId"
    }
}

/**
 * Lab Log 试用版 App 主界面
 */
@OptIn(ExperimentalPermissionsApi::class, ExperimentalMaterial3Api::class)
@Composable
fun LabLogTrialApp() {
    val navController = rememberNavController()
    val cameraPermissionState = rememberPermissionState(Manifest.permission.CAMERA)
    
    // 请求相机权限
    LaunchedEffect(Unit) {
        if (!cameraPermissionState.status.isGranted) {
            cameraPermissionState.launchPermissionRequest()
        }
    }
    
    if (!cameraPermissionState.status.isGranted) {
        // 权限未授予，显示提示
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                Text("需要相机权限才能使用此应用")
                Button(onClick = { cameraPermissionState.launchPermissionRequest() }) {
                    Text("授予权限")
                }
            }
        }
    } else {
        // 权限已授予，显示主界面
        MainScreen(navController)
    }
}

/**
 * 主界面（带导航）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(navController: NavHostController) {
    val currentBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = currentBackStackEntry?.destination?.route
    
    // 获取使用次数
    val usageCount = UsageCounter.getCount(androidx.compose.ui.platform.LocalContext.current)
    
    Scaffold(
        topBar = {
            // 只在录制和历史记录页面显示标题栏
            if (currentRoute == Screen.Recording.route || currentRoute == Screen.History.route) {
                TopAppBar(
                    title = {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "Lab Log 试用版",
                                fontWeight = FontWeight.Bold
                            )
                            Text(
                                text = "已理解 $usageCount 次",
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                    }
                )
            }
        },
        bottomBar = {
            // 只在录制和历史记录页面显示底部导航栏
            if (currentRoute == Screen.Recording.route || currentRoute == Screen.History.route) {
                NavigationBar {
                    NavigationBarItem(
                        selected = currentRoute == Screen.Recording.route,
                        onClick = {
                            if (currentRoute != Screen.Recording.route) {
                                navController.navigate(Screen.Recording.route) {
                                    popUpTo(Screen.Recording.route) { inclusive = true }
                                }
                            }
                        },
                        icon = { Icon(Icons.Default.VideoCall, contentDescription = "录制") },
                        label = { Text("录制") }
                    )
                    NavigationBarItem(
                        selected = currentRoute == Screen.History.route,
                        onClick = {
                            if (currentRoute != Screen.History.route) {
                                navController.navigate(Screen.History.route) {
                                    popUpTo(Screen.Recording.route)
                                }
                            }
                        },
                        icon = { Icon(Icons.Default.History, contentDescription = "历史") },
                        label = { Text("历史") }
                    )
                }
            }
        }
    ) { paddingValues ->
        NavHost(
            navController = navController,
            startDestination = Screen.Recording.route,
            modifier = Modifier.padding(paddingValues)
        ) {
            // 录制界面
            composable(Screen.Recording.route) {
                RecordingScreen(
                    onNavigateToDetail = { videoId ->
                        navController.navigate(Screen.Detail.createRoute(videoId))
                    }
                )
            }
            
            // 历史记录界面
            composable(Screen.History.route) {
                HistoryScreen(
                    onNavigateToDetail = { videoId ->
                        navController.navigate(Screen.Detail.createRoute(videoId))
                    }
                )
            }
            
            // 详情页
            composable(
                route = Screen.Detail.route,
                arguments = listOf(navArgument("videoId") { type = NavType.StringType })
            ) { backStackEntry ->
                val videoId = backStackEntry.arguments?.getString("videoId") ?: return@composable
                DetailScreen(
                    videoId = videoId,
                    onNavigateBack = {
                        navController.popBackStack()
                    }
                )
            }
        }
    }
}

