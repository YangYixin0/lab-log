#!/usr/bin/env python3
"""
FPS监控器：负责统计和计算帧率
"""
from datetime import datetime


class FPSMonitor:
    """FPS统计和监控"""
    
    def __init__(self):
        """初始化FPS监控器"""
        self.frame_count = 0  # 总帧数
        self.fps_counter = 0  # 当前统计周期内的帧数
        self.last_fps_time = None  # 上次FPS统计时间
        self.current_fps = 0.0  # 当前FPS值
    
    def reset(self):
        """重置所有统计"""
        self.frame_count = 0
        self.fps_counter = 0
        self.last_fps_time = datetime.now()
        self.current_fps = 0.0
    
    def update(self) -> tuple[float, int]:
        """
        更新帧计数，如果超过1秒则计算FPS
        
        Returns:
            tuple: (fps, total_frames) 如果达到统计时间，否则返回 (None, total_frames)
        """
        self.frame_count += 1
        self.fps_counter += 1
        
        current_time = datetime.now()
        
        # 初始化时间
        if self.last_fps_time is None:
            self.last_fps_time = current_time
            return (None, self.frame_count)
        
        # 计算时间差
        time_diff = (current_time - self.last_fps_time).total_seconds()
        
        # 如果超过1秒，计算FPS
        if time_diff >= 1.0:
            self.current_fps = self.fps_counter / time_diff
            fps = self.current_fps
            total_frames = self.frame_count
            
            # 重置计数器
            self.fps_counter = 0
            self.last_fps_time = current_time
            
            return (fps, total_frames)
        
        return (None, self.frame_count)
    
    def get_fps(self) -> float:
        """获取当前FPS值"""
        return self.current_fps
    
    def get_total_frames(self) -> int:
        """获取总帧数"""
        return self.frame_count

