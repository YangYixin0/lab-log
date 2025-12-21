"""监控和统计模块"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class MonitoringLogger:
    """监控日志记录器"""
    
    def __init__(self, log_file: Optional[Path] = None):
        """
        初始化监控日志记录器
        
        Args:
            log_file: 日志文件路径，如果为None则使用默认路径
        """
        if log_file is None:
            log_dir = Path("logs_debug")
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "processing_stats.jsonl"
        
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def log_segment_processing(self, stats: Dict[str, Any]) -> None:
        """
        记录分段处理统计
        
        Args:
            stats: 统计信息字典，包含：
                - segment_id: 分段ID
                - segment_duration: 分段时长（秒）
                - processing_time: 处理用时（秒）
                - queue_length: 处理时的队列长度
                - events_count: 识别的事件数量
                - timestamp: 处理完成时间戳
                - h264_size_mb: H264文件大小（MB）
                - mp4_size_mb: MP4文件大小（MB）
        """
        # 添加时间戳（如果未提供）
        if 'timestamp' not in stats:
            stats['timestamp'] = datetime.now().isoformat()
        
        # 写入JSONL文件
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            print(f"[Warning]: 写入监控日志失败: {e}")
    
    def print_segment_stats(self, stats: Dict[str, Any]) -> None:
        """
        打印分段处理统计到控制台
        
        Args:
            stats: 统计信息字典
        """
        segment_id = stats.get('segment_id', 'unknown')
        segment_duration = stats.get('segment_duration', 0)
        processing_time = stats.get('processing_time', 0)
        queue_length = stats.get('queue_length', 0)
        events_count = stats.get('events_count', 0)
        h264_size_mb = stats.get('h264_size_mb', 0)
        mp4_size_mb = stats.get('mp4_size_mb', 0)
        
        print(f"[Realtime] 分段 {segment_id} 处理完成")
        print(f"  - 分段时长: {segment_duration:.2f} 秒")
        print(f"  - 处理用时: {processing_time:.2f} 秒")
        print(f"  - 队列长度: {queue_length}")
        print(f"  - 识别事件: {events_count} 个")
        if h264_size_mb > 0:
            print(f"  - 已删除H264: {h264_size_mb:.2f} MB")
        if mp4_size_mb > 0:
            print(f"  - 保留MP4: {mp4_size_mb:.2f} MB")
    
    def print_queue_warning(self, queue_length: int, threshold: int) -> None:
        """
        打印队列告警
        
        Args:
            queue_length: 当前队列长度
            threshold: 告警阈值
        """
        print(f"[Warning] 处理队列长度 ({queue_length}) 超过阈值 ({threshold})，处理速度可能慢于采集速度")

