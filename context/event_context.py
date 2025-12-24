"""当天事件缓存查询：从 JSONL 文件获取最新事件用于模型上下文"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional


class EventContext:
    """事件上下文管理器：从 JSONL 文件查询当天最新事件"""
    
    def __init__(self, event_log_file: Optional[str] = None):
        """
        初始化事件上下文
        
        Args:
            event_log_file: 事件日志文件路径，如果为 None 则使用默认路径 logs_debug/event_logs.jsonl
        """
        if event_log_file is None:
            # 默认使用项目根目录下的 logs_debug/event_logs.jsonl
            # event_context.py 在 context/ 目录下，所以 parent.parent 是项目根目录
            project_root = Path(__file__).parent.parent
            self.event_log_file = project_root / "logs_debug" / "event_logs.jsonl"
        else:
            self.event_log_file = Path(event_log_file)
    
    def get_recent_events(self, n: int = 20, date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        获取当天最新 n 条事件
        
        Args:
            n: 返回的最大事件数
            date: 指定日期，默认为今天
        
        Returns:
            事件列表，每个事件包含简化字段：
            - event_id: 事件ID
            - start_time: 开始时间 (ISO格式)
            - end_time: 结束时间 (ISO格式)
            - event_type: 事件类型
            - person_ids: 人物编号列表
            - equipment: 设备名称
            - description: 事件描述
        """
        if date is None:
            date = datetime.now()
        
        # 构建当天的时间范围
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        # 查询当天的事件
        raw_events = self._query_today_events(day_start, day_end, n)
        
        # 转换为简化格式
        return [self._simplify_event(event) for event in raw_events]
    
    def _query_today_events(self, day_start: datetime, day_end: datetime, 
                            limit: int) -> List[Dict[str, Any]]:
        """从 JSONL 文件查询当天事件的原始数据"""
        if not self.event_log_file.exists():
            return []
        
        events = []
        try:
            # 读取 JSONL 文件的所有行
            with open(self.event_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        event = json.loads(line)
                        # 解析时间
                        start_time_str = event.get('start_time', '')
                        if not start_time_str:
                            continue
                        
                        # 解析 ISO 格式时间
                        try:
                            if 'T' in start_time_str:
                                event_start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            else:
                                continue
                        except (ValueError, AttributeError):
                            continue
                        
                        # 过滤当天的数据
                        if day_start <= event_start < day_end:
                            events.append(event)
                    except json.JSONDecodeError:
                        # 跳过无效的 JSON 行
                        continue
            
            # 按时间降序排序（最新的在前）
            events.sort(key=lambda x: x.get('start_time', ''), reverse=True)
            
            # 返回最新的 n 条
            return events[:limit]
            
        except Exception as e:
            print(f"从 JSONL 文件查询当天事件失败: {e}")
            return []
    
    def _simplify_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        将原始事件数据转换为简化格式（用于模型提示）
        
        Args:
            event: 原始事件数据
        
        Returns:
            简化的事件数据
        """
        # 解析 structured 字段
        structured = event.get('structured', {})
        if isinstance(structured, str):
            try:
                structured = json.loads(structured)
            except json.JSONDecodeError:
                structured = {}
        
        # 提取 person_ids
        person_ids = []
        if 'person_ids' in structured:
            # 新格式：直接使用 person_ids 列表
            person_ids = structured.get('person_ids', [])
        elif 'person' in structured:
            # 旧格式：从 person 字段提取
            person = structured.get('person', {})
            if isinstance(person, dict) and 'person_id' in person:
                person_ids = [person['person_id']]
        
        # 提取设备名称
        equipment = structured.get('equipment', '')
        
        # 格式化时间
        start_time = event.get('start_time')
        end_time = event.get('end_time')
        if isinstance(start_time, datetime):
            start_time = start_time.strftime('%Y-%m-%dT%H:%M:%S')
        if isinstance(end_time, datetime):
            end_time = end_time.strftime('%Y-%m-%dT%H:%M:%S')
        
        return {
            'event_id': event.get('event_id', ''),
            'start_time': start_time,
            'end_time': end_time,
            'event_type': event.get('event_type', ''),
            'person_ids': person_ids,
            'equipment': equipment,
            'description': event.get('raw_text', '')
        }
    
    def get_max_event_id_number(self, date: Optional[datetime] = None) -> int:
        """
        获取当天最大事件编号数字（从 JSONL 文件读取）
        
        Args:
            date: 指定日期，默认为今天
        
        Returns:
            最大事件编号数字，如果没有事件则返回 0
        """
        if date is None:
            date = datetime.now()
        
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        if not self.event_log_file.exists():
            return 0
        
        max_num = 0
        try:
            with open(self.event_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        event = json.loads(line)
                        # 检查是否是当天的数据
                        start_time_str = event.get('start_time', '')
                        if not start_time_str:
                            continue
                        
                        try:
                            if 'T' in start_time_str:
                                event_start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            else:
                                continue
                        except (ValueError, AttributeError):
                            continue
                        
                        if day_start <= event_start < day_end:
                            event_id = event.get('event_id', '')
                            # 从 event_id 中提取数字（格式如 evt_00042）
                            match = re.search(r'(\d+)$', event_id)
                            if match:
                                num = int(match.group(1))
                                if num > max_num:
                                    max_num = num
                    except (json.JSONDecodeError, ValueError):
                        continue
            
            return max_num
        except Exception as e:
            print(f"从 JSONL 文件获取最大事件编号失败: {e}")
            return 0
    
    def format_for_prompt(self, events: List[Dict[str, Any]]) -> str:
        """
        将事件列表格式化为提示词中的文本
        
        Args:
            events: 简化后的事件列表
        
        Returns:
            格式化的文本，用于嵌入提示词
        """
        if not events:
            return "（暂无事件记录）"
        
        lines = []
        for event in events:
            person_str = ", ".join(event['person_ids']) if event['person_ids'] else "-"
            equipment_str = event['equipment'] if event['equipment'] else "-"
            
            line = (
                f"- {event['event_id']} | "
                f"{event['start_time']} ~ {event['end_time']} | "
                f"{event['event_type']} | "
                f"人物: {person_str} | "
                f"设备: {equipment_str} | "
                f"{event['description']}"
            )
            lines.append(line)
        
        return "\n".join(lines)
    
    def close(self):
        """关闭资源（JSONL 文件模式无需关闭）"""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


