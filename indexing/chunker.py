"""日志分块（按时间窗口聚合）"""

import uuid
from datetime import datetime, timedelta
from typing import List

from storage.models import EventLog, LogChunk


class LogChunker:
    """日志分块器"""
    
    def __init__(self, chunk_duration_minutes: float = 7.5):
        """
        初始化分块器
        
        Args:
            chunk_duration_minutes: 分块时长（分钟），默认 7.5 分钟（5-10 分钟的中间值）
        """
        self.chunk_duration = timedelta(minutes=chunk_duration_minutes)
    
    def chunk_events(self, events: List[EventLog]) -> List[LogChunk]:
        """
        按时间窗口聚合事件日志
        
        Args:
            events: 事件日志列表（应按时间排序）
        
        Returns:
            日志分块列表
        """
        if not events:
            return []
        
        # 按开始时间排序
        sorted_events = sorted(events, key=lambda e: e.start_time)
        
        chunks = []
        current_chunk_events = []
        chunk_start_time = sorted_events[0].start_time
        chunk_end_time = chunk_start_time + self.chunk_duration
        
        for event in sorted_events:
            # 如果事件在当前分块的时间窗口内
            if event.start_time < chunk_end_time:
                current_chunk_events.append(event)
                # 更新分块结束时间（使用事件的最晚时间）
                if event.end_time > chunk_end_time:
                    chunk_end_time = event.end_time
            else:
                # 创建新分块
                if current_chunk_events:
                    chunk = self._create_chunk(current_chunk_events, chunk_start_time, chunk_end_time)
                    chunks.append(chunk)
                
                # 开始新分块
                current_chunk_events = [event]
                chunk_start_time = event.start_time
                chunk_end_time = chunk_start_time + self.chunk_duration
        
        # 处理最后一个分块
        if current_chunk_events:
            chunk = self._create_chunk(current_chunk_events, chunk_start_time, chunk_end_time)
            chunks.append(chunk)
        
        return chunks
    
    def _create_chunk(self, events: List[EventLog], start_time: datetime, end_time: datetime) -> LogChunk:
        """创建分块"""
        chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
        
        # 拼接 raw_text
        chunk_text = "\n".join([event.raw_text for event in events if event.raw_text])
        
        # 提取 event_id 列表
        related_event_ids = [event.event_id for event in events]
        
        return LogChunk(
            chunk_id=chunk_id,
            chunk_text=chunk_text,
            related_event_ids=related_event_ids,
            start_time=start_time,
            end_time=end_time,
            embedding=None  # 嵌入向量稍后生成
        )

