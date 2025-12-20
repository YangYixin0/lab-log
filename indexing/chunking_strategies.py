"""分块策略实现"""

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List

from storage.models import EventLog, LogChunk


class ChunkingStrategy(ABC):
    """分块策略抽象基类"""
    
    @abstractmethod
    def chunk_events(self, events: List[EventLog]) -> List[LogChunk]:
        """
        将事件列表分块
        
        Args:
            events: 事件日志列表
            
        Returns:
            日志分块列表
        """
        pass
    
    def _create_chunk(self, events: List[EventLog], start_time: datetime, end_time: datetime) -> LogChunk:
        """
        创建分块对象
        
        Args:
            events: 该分块包含的事件列表
            start_time: 分块开始时间
            end_time: 分块结束时间
            
        Returns:
            LogChunk 对象
        """
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


class EventPerChunkStrategy(ChunkingStrategy):
    """每个事件一个分块的策略"""
    
    def chunk_events(self, events: List[EventLog]) -> List[LogChunk]:
        """
        每个事件创建一个独立的分块
        
        Args:
            events: 事件日志列表
            
        Returns:
            日志分块列表（每个事件一个分块）
        """
        if not events:
            return []
        
        chunks = []
        for event in events:
            chunk = self._create_chunk(
                events=[event],
                start_time=event.start_time,
                end_time=event.end_time
            )
            chunks.append(chunk)
        
        return chunks


class TimeWindowChunkingStrategy(ChunkingStrategy):
    """按时间窗口聚合事件的策略"""
    
    def __init__(self, chunk_duration_minutes: float = 7.5):
        """
        初始化时间窗口分块策略
        
        Args:
            chunk_duration_minutes: 分块时长（分钟），默认 7.5 分钟
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


class NoPersonIntervalChunkingStrategy(ChunkingStrategy):
    """以无人事件为间隔来分块的策略"""
    
    def chunk_events(self, events: List[EventLog]) -> List[LogChunk]:
        """
        以无人事件（person.present = false）为间隔来分块
        
        策略：
        - 遇到无人事件时，将无人事件添加到当前分块（放在时间较早的块里）
        - 然后结束当前分块并开始新分块
        - 无人事件参与分块，作为分块的结束标记
        
        Args:
            events: 事件日志列表
            
        Returns:
            日志分块列表
        """
        if not events:
            return []
        
        # 按开始时间排序
        sorted_events = sorted(events, key=lambda e: e.start_time)
        
        chunks = []
        current_chunk_events = []
        
        for event in sorted_events:
            # 检查是否是无人事件
            is_no_person = (
                isinstance(event.structured, dict) and
                event.structured.get('person', {}).get('present', True) == False
            )
            
            if is_no_person:
                # 将无人事件添加到当前分块（放在时间较早的块里）
                current_chunk_events.append(event)
                
                # 如果当前分块有事件，创建分块
                if current_chunk_events:
                    chunk = self._create_chunk(
                        events=current_chunk_events,
                        start_time=current_chunk_events[0].start_time,
                        end_time=current_chunk_events[-1].end_time
                    )
                    chunks.append(chunk)
                    current_chunk_events = []
            else:
                # 有人的事件，添加到当前分块
                current_chunk_events.append(event)
        
        # 处理最后一个分块（可能没有无人事件作为结束标记）
        if current_chunk_events:
            chunk = self._create_chunk(
                events=current_chunk_events,
                start_time=current_chunk_events[0].start_time,
                end_time=current_chunk_events[-1].end_time
            )
            chunks.append(chunk)
        
        return chunks


class LLMChunkingStrategy(ChunkingStrategy):
    """使用 LLM 进行智能分块的策略（预留接口）"""
    
    def __init__(self, llm_service=None, max_chunk_size: int = 500):
        """
        初始化 LLM 分块策略
        
        Args:
            llm_service: LLM 服务实例（用于智能分块）
            max_chunk_size: 最大分块大小（字符数）
        """
        self.llm_service = llm_service
        self.max_chunk_size = max_chunk_size
    
    def chunk_events(self, events: List[EventLog]) -> List[LogChunk]:
        """
        使用 LLM 进行智能分块
        
        注意：这是一个预留接口，实际实现需要：
        1. 将事件文本发送给 LLM
        2. LLM 根据语义相关性进行分块
        3. 返回分块结果
        
        Args:
            events: 事件日志列表
            
        Returns:
            日志分块列表
        """
        # TODO: 实现 LLM 智能分块逻辑
        # 目前作为占位符，回退到每个事件一个块
        if not events:
            return []
        
        # 临时实现：回退到每个事件一个块
        strategy = EventPerChunkStrategy()
        return strategy.chunk_events(events)

