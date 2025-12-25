"""分段时间解析工具函数"""

import time
from datetime import datetime
from typing import Tuple, Optional


def extract_date_from_segment_id(segment_id: str) -> Optional[datetime]:
    """
    从 segment_id 中提取日期
    
    segment_id 格式：YYYYMMDD_HHMMSS_XX
    例如：20251221_195713_00
    
    Args:
        segment_id: 分段ID，格式为 YYYYMMDD_HHMMSS_XX
    
    Returns:
        datetime 对象，如果解析失败则返回 None
    """
    try:
        parts = segment_id.split('_')
        if len(parts) >= 2:
            date_str = parts[0]  # 20251221
            # 解析日期部分
            segment_date = datetime.strptime(date_str, "%Y%m%d")
            return segment_date
    except Exception:
        pass
    
    return None


def parse_segment_times(segment_id: str, target_duration: float) -> Tuple[float, float]:
    """
    从 segment_id 中解析分段的开始和结束时间
    
    segment_id 格式：YYYYMMDD_HHMMSS_XX
    例如：20251221_195713_00
    
    Args:
        segment_id: 分段ID，格式为 YYYYMMDD_HHMMSS_XX
        target_duration: 目标分段时长（秒），用于计算结束时间
    
    Returns:
        (start_time, end_time) 元组，单位为秒（Unix 时间戳）
        如果解析失败，返回当前时间和当前时间+target_duration
    """
    try:
        parts = segment_id.split('_')
        if len(parts) >= 2:
            date_str = parts[0]  # 20251221
            time_str = parts[1]  # 195713
            timestamp_str = f"{date_str}_{time_str}"
            
            # 解析为 datetime 对象
            segment_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            start_time = segment_time.timestamp()
            # 估算结束时间（假设分段时长为 target_duration）
            end_time = start_time + target_duration
            return start_time, end_time
    except Exception:
        pass
    
    # 如果解析失败，使用当前时间
    current_time = time.time()
    return current_time, current_time + target_duration


