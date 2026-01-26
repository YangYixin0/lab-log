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
    qr_results: List[Dict[str, Any]] = field(default_factory=list)  # OCR/QR 识别结果，默认空列表


@dataclass
class EventLog:
    """
    事件日志（系统最小原子）
    
    structured 字段格式（动态上下文版本）:
    {
        "person_ids": ["p1", "p2"],  # 涉及的人物编号列表
        "equipment": "离心机",        # 设备名称
    }
    
    旧格式（兼容模式）:
    {
        "person": {
            "upper_clothing_color": "白色",
            "hair_color": "黑色",
            "action": "操作设备"
        },
        "equipment": "离心机"
    }
    """
    event_id: str
    segment_id: str
    start_time: datetime
    end_time: datetime
    event_type: Optional[str] = None  # 事件类型，如 "person"、"equipment-only"、"none"
    structured: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""  # 事件的自然语言描述（不含外貌信息）


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


@dataclass
class Emergency:
    """紧急情况"""
    emergency_id: str
    description: str
    start_time: datetime
    end_time: datetime
    segment_id: str
    status: str = "PENDING"  # PENDING, RESOLVED
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

