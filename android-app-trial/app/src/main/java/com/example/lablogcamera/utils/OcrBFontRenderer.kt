package com.example.lablogcamera.utils

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.util.Log

private const val TAG = "OcrBFontRenderer"

/**
 * OCR-B 字体渲染器
 * 用于在视频帧上绘制时间戳水印
 */
object OcrBFontRenderer {
    private const val FONT_ASSET_PATH = "fonts/OCRB_Regular.ttf"
    
    // 字体对象，可能是 OCR-B 或系统等宽字体
    private var typeface: Typeface? = null
    
    // 字符位图缓存 (字符 -> 位图数组)
    private val charBitmapCache = mutableMapOf<Char, Array<IntArray>>()
    
    // 预加载完成标志
    @Volatile
    private var preloadCompleted = false
    
    // 需要预加载的字符集（时间戳 "YYYY-MM-DDTHH:mm:ss" 所需）
    private const val PRELOAD_CHARS = "0123456789-: Time"
    
    /**
     * 初始化字体渲染器，加载 OCR-B 字体
     * @param context Android Context，用于访问 AssetManager
     */
    fun initialize(context: Context) {
        try {
            // 尝试从 Assets 加载 OCR-B 字体
            typeface = Typeface.createFromAsset(context.assets, FONT_ASSET_PATH)
            Log.d(TAG, "Successfully loaded OCR-B font from $FONT_ASSET_PATH")
        } catch (e: Exception) {
            // 加载失败，回退到系统等宽字体
            Log.e(TAG, "Failed to load OCR-B font, falling back to MONOSPACE", e)
            typeface = Typeface.MONOSPACE
        }
    }
    
    /**
     * 预加载所有时间戳所需的字符位图
     * 应在后台线程调用
     * @param width 字符宽度
     * @param height 字符高度
     */
    fun preloadAllCharacters(width: Int, height: Int) {
        if (typeface == null) {
            Log.e(TAG, "Typeface not initialized, cannot preload characters")
            return
        }
        
        val startTime = System.currentTimeMillis()
        Log.d(TAG, "Starting to preload ${PRELOAD_CHARS.length} characters at ${width}x${height}")
        
        try {
            // 批量渲染所有字符
            PRELOAD_CHARS.forEach { char ->
                val bitmap = renderCharBitmap(char, width, height)
                charBitmapCache[char] = bitmap
            }
            
            preloadCompleted = true
            val duration = System.currentTimeMillis() - startTime
            Log.d(TAG, "Preload completed in ${duration}ms, cached ${charBitmapCache.size} characters")
        } catch (e: Exception) {
            Log.e(TAG, "Error during preload", e)
            preloadCompleted = false
        }
    }
    
    /**
     * 获取缓存的字符位图
     * @param char 要获取的字符
     * @return 字符位图，如果预加载未完成或字符不存在则返回 null
     */
    fun getCachedCharBitmap(char: Char): Array<IntArray>? {
        if (!preloadCompleted) {
            Log.w(TAG, "Preload not completed yet, cannot get char bitmap for '$char'")
            return null
        }
        return charBitmapCache[char]
    }
    
    /**
     * 渲染单个字符的位图
     * @param char 要渲染的字符
     * @param width 目标宽度
     * @param height 目标高度
     * @return 字符位图数组 (行 x 列)，1=白色，0=背景
     */
    private fun renderCharBitmap(char: Char, width: Int, height: Int): Array<IntArray> {
        // 创建临时位图 (ALPHA_8 格式，单通道)
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ALPHA_8)
        val canvas = Canvas(bitmap)
        
        // 配置画笔
        val paint = Paint().apply {
            this.typeface = this@OcrBFontRenderer.typeface
            this.isAntiAlias = true  // 抗锯齿
            this.textAlign = Paint.Align.CENTER
            this.color = android.graphics.Color.WHITE
            
            // 计算合适的字体大小
            // 初始字体大小为高度的 85%
            var testSize = height * 0.85f
            this.textSize = testSize
            
            // 测量字符宽度，如果超出目标宽度则缩小
            val charStr = char.toString()
            var textWidth = measureText(charStr)
            while (textWidth > width && testSize > 1f) {
                testSize -= 0.5f
                this.textSize = testSize
                textWidth = measureText(charStr)
            }
        }
        
        // 计算居中绘制位置
        val x = width / 2f
        val fontMetrics = paint.fontMetrics
        val textHeight = fontMetrics.descent - fontMetrics.ascent
        val y = (height - textHeight) / 2f - fontMetrics.ascent
        
        // 绘制字符
        canvas.drawText(char.toString(), x, y, paint)
        
        // 提取像素数据并转换为二维数组
        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
        
        val result = Array(height) { IntArray(width) }
        for (row in 0 until height) {
            for (col in 0 until width) {
                val pixelIndex = row * width + col
                // Alpha 通道值 > 128 视为白色 (1)，否则为背景 (0)
                val alpha = (pixels[pixelIndex] shr 24) and 0xFF
                result[row][col] = if (alpha > 128) 1 else 0
            }
        }
        
        // 回收临时位图
        bitmap.recycle()
        
        return result
    }
    
    /**
     * 清空缓存（用于内存管理）
     */
    fun clearCache() {
        charBitmapCache.clear()
        preloadCompleted = false
        Log.d(TAG, "Cache cleared")
    }
    
    /**
     * 检查预加载是否完成
     */
    fun isPreloadCompleted(): Boolean = preloadCompleted
}

/**
 * 在 NV12 数据的 Y 平面上绘制时间戳水印
 * @param nv12 NV12 字节数组（Y 平面在前，UV 平面在后）
 * @param width 图像宽度
 * @param height 图像高度
 * @param timestamp 时间戳字符串（格式："Time: hh:mm:ss"）
 * @param charWidth 字符宽度
 * @param charHeight 字符高度
 * @param offsetX 左上角 X 偏移（默认 10）
 * @param offsetY 左上角 Y 偏移（默认 10）
 */
fun drawTimestampOnNv12(
    nv12: ByteArray,
    width: Int,
    height: Int,
    timestamp: String,
    charWidth: Int = 20,
    charHeight: Int = 30,
    offsetX: Int = 10,
    offsetY: Int = 10
) {
    // 检查预加载是否完成
    if (!OcrBFontRenderer.isPreloadCompleted()) {
        Log.w(TAG, "OcrBFontRenderer preload not completed, skipping watermark")
        return
    }
    
    // 确保偏移为偶数
    val x = (offsetX / 2) * 2
    val y = (offsetY / 2) * 2
    
    // 计算文本区域大小
    val textWidth = timestamp.length * charWidth
    val textHeight = charHeight
    val padding = 4
    val bgWidth = textWidth + padding * 2
    val bgHeight = textHeight + padding * 2
    
    // 确保背景区域不越界
    if (x + bgWidth > width || y + bgHeight > height) {
        return
    }
    
    // 绘制黑色背景矩形
    val bgY = 0.toByte()  // 黑色
    for (row in y until (y + bgHeight).coerceAtMost(height)) {
        for (col in x until (x + bgWidth).coerceAtMost(width)) {
            val index = row * width + col
            if (index < nv12.size) {
                nv12[index] = bgY
            }
        }
    }
    
    // 绘制白色文字（使用 OCR-B 字体渲染器）
    val textStartX = x + padding
    val textStartY = y + padding
    var charOffsetX = 0
    
    for (char in timestamp) {
        // 从缓存获取字符位图
        val charBitmap = OcrBFontRenderer.getCachedCharBitmap(char)
        if (charBitmap == null) {
            Log.w(TAG, "Character '$char' not found in cache, skipping")
            charOffsetX += charWidth
            continue
        }
        
        // 绘制字符
        for (row in 0 until charHeight) {
            for (col in 0 until charWidth) {
                val dstY = textStartY + row
                val dstX = textStartX + charOffsetX + col
                
                if (dstY < height && dstX < width) {
                    val index = dstY * width + dstX
                    if (index < nv12.size) {
                        if (charBitmap[row][col] == 1) {
                            nv12[index] = 255.toByte()  // 白色
                        }
                    }
                }
            }
        }
        
        charOffsetX += charWidth
    }
}

