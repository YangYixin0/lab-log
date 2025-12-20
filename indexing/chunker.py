"""日志分块器（策略模式）"""

from typing import List

from storage.models import EventLog, LogChunk
from indexing.chunking_strategies import (
    ChunkingStrategy,
    EventPerChunkStrategy,
    TimeWindowChunkingStrategy,
    NoPersonIntervalChunkingStrategy,
    LLMChunkingStrategy
)


class LogChunker:
    """日志分块器（使用策略模式）"""
    
    def __init__(self, strategy: ChunkingStrategy = None):
        """
        初始化分块器
        
        Args:
            strategy: 分块策略，如果为 None 则使用默认策略（每个事件一个块）
        """
        self.strategy = strategy or EventPerChunkStrategy()
    
    def chunk_events(self, events: List[EventLog]) -> List[LogChunk]:
        """
        将事件列表分块
        
        Args:
            events: 事件日志列表
            
        Returns:
            日志分块列表
        """
        return self.strategy.chunk_events(events)
    
    @classmethod
    def create_with_time_window(cls, chunk_duration_minutes: float = 7.5) -> 'LogChunker':
        """
        创建使用时间窗口策略的分块器
        
        Args:
            chunk_duration_minutes: 分块时长（分钟）
            
        Returns:
            LogChunker 实例
        """
        strategy = TimeWindowChunkingStrategy(chunk_duration_minutes)
        return cls(strategy)
    
    @classmethod
    def create_with_no_person_interval(cls) -> 'LogChunker':
        """
        创建使用无人事件间隔策略的分块器
        
        Returns:
            LogChunker 实例
        """
        strategy = NoPersonIntervalChunkingStrategy()
        return cls(strategy)
    
    @classmethod
    def create_with_llm(cls, llm_service=None, max_chunk_size: int = 500) -> 'LogChunker':
        """
        创建使用 LLM 智能分块策略的分块器
        
        Args:
            llm_service: LLM 服务实例
            max_chunk_size: 最大分块大小（字符数）
            
        Returns:
            LogChunker 实例
        """
        strategy = LLMChunkingStrategy(llm_service, max_chunk_size)
        return cls(strategy)
