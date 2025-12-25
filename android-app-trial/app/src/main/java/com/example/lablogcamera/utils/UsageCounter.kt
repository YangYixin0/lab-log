package com.example.lablogcamera.utils

import android.content.Context
import android.content.SharedPreferences

/**
 * 使用次数计数器
 * 管理 API 调用次数限制
 */
object UsageCounter {
    private const val PREF_NAME = "usage_counter"
    private const val KEY_API_CALLS = "api_calls"
    
    private fun getPrefs(context: Context): SharedPreferences {
        return context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
    }
    
    /**
     * 增加计数并检查是否超过限制
     * @param context Context
     * @param maxCalls 最大允许次数
     * @return true 如果允许继续使用，false 如果已达上限
     */
    fun incrementAndCheck(context: Context, maxCalls: Int): Boolean {
        val prefs = getPrefs(context)
        val currentCount = prefs.getInt(KEY_API_CALLS, 0)
        
        if (currentCount >= maxCalls) {
            return false
        }
        
        prefs.edit().putInt(KEY_API_CALLS, currentCount + 1).apply()
        return true
    }
    
    /**
     * 获取当前使用次数
     */
    fun getCount(context: Context): Int {
        return getPrefs(context).getInt(KEY_API_CALLS, 0)
    }
    
    /**
     * 获取剩余使用次数
     */
    fun getRemainingCount(context: Context, maxCalls: Int): Int {
        val current = getCount(context)
        return maxOf(0, maxCalls - current)
    }
    
    /**
     * 检查是否可以使用（不增加计数）
     */
    fun canUse(context: Context, maxCalls: Int): Boolean {
        return getCount(context) < maxCalls
    }
    
    /**
     * 重置计数（仅用于测试或管理）
     */
    fun reset(context: Context) {
        getPrefs(context).edit().putInt(KEY_API_CALLS, 0).apply()
    }
}

