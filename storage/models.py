"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional


@dataclass
class VideoSegment:
    """视频分段"""
    segment_id: str
    video_path: str
    start_time: float  # seconds in video
    end_time: float


@dataclass
class EventLog:
    """事件日志（系统最小原子）"""
    event_id: str
    segment_id: str
    start_time: datetime
    end_time: datetime
    event_type: Optional[str] = None  # 事件类型，如 "person"、"equipment-only"
    structured: Dict[str, Any] = field(default_factory=dict)  # 固定 schema
    raw_text: str = ""


@dataclass
class VideoUnderstandingResult:
    """视频理解结果"""
    segment_id: str
    remark: str
    events: List[EventLog] = field(default_factory=list)


@dataclass
class LogChunk:
    """日志分块"""
    chunk_id: str
    chunk_text: str
    related_event_ids: List[str]
    start_time: datetime
    end_time: datetime
    embedding: Optional[List[float]] = None  # 1024 维向量

