"""当天事件缓存查询：从数据库获取最新事件用于模型上下文"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from storage.seekdb_client import SeekDBClient


class EventContext:
    """事件上下文管理器：查询当天最新事件"""
    
    def __init__(self, db_client: Optional[SeekDBClient] = None):
        """
        初始化事件上下文
        
        Args:
            db_client: 数据库客户端，如果为 None 则创建默认实例
        """
        self.db_client = db_client or SeekDBClient()
        self._owns_db_client = db_client is None
    
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
        """查询当天事件的原始数据"""
        self.db_client._ensure_connected()
        
        sql = """
            SELECT event_id, segment_id, start_time, end_time, 
                   event_type, structured, raw_text
            FROM logs_raw
            WHERE start_time >= %s AND start_time < %s
            ORDER BY start_time DESC
            LIMIT %s
        """
        
        try:
            with self.db_client.connection.cursor() as cursor:
                cursor.execute(sql, (day_start, day_end, limit))
                results = cursor.fetchall()
                return list(results)
        except Exception as e:
            print(f"查询当天事件失败: {e}")
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
        获取当天最大事件编号数字
        
        Args:
            date: 指定日期，默认为今天
        
        Returns:
            最大事件编号数字，如果没有事件则返回 0
        """
        if date is None:
            date = datetime.now()
        
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        self.db_client._ensure_connected()
        
        sql = """
            SELECT event_id
            FROM logs_raw
            WHERE start_time >= %s AND start_time < %s
            ORDER BY event_id DESC
            LIMIT 1
        """
        
        try:
            with self.db_client.connection.cursor() as cursor:
                cursor.execute(sql, (day_start, day_end))
                result = cursor.fetchone()
                if result and result.get('event_id'):
                    # 从 event_id 中提取数字（格式如 evt_00042）
                    event_id = result['event_id']
                    # 提取最后的数字部分
                    import re
                    match = re.search(r'(\d+)$', event_id)
                    if match:
                        return int(match.group(1))
                return 0
        except Exception as e:
            print(f"获取最大事件编号失败: {e}")
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
        """关闭资源"""
        if self._owns_db_client and self.db_client:
            self.db_client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

