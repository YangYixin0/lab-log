"""日志写入器（字段加密、写入数据库和 JSONL 文件）"""

import json
from pathlib import Path
from typing import Dict, Any

from config.encryption_config import EncryptionConfig
from log_writer.encryption_service import FieldEncryptionService
from storage.seekdb_client import SeekDBClient
from storage.models import EventLog


class LogWriter:
    """日志写入器"""
    
    def __init__(self, db_client: SeekDBClient, 
                 encryption_service: FieldEncryptionService = None,
                 debug_log_dir: str = "logs_debug"):
        """
        初始化写入器
        
        Args:
            db_client: 数据库客户端
            encryption_service: 加密服务，如果为 None 则创建默认实例
            debug_log_dir: 调试日志目录
        """
        self.db = db_client
        self.encryption_service = encryption_service or FieldEncryptionService()
        self.debug_log_dir = Path(debug_log_dir)
        self.debug_log_dir.mkdir(parents=True, exist_ok=True)
    
    def write_event_log(self, event_log: EventLog) -> None:
        """
        写入事件日志（字段加密、写入数据库和 JSONL 文件）
        
        Args:
            event_log: 事件日志
        """
        # 深拷贝 structured 避免修改原数据
        structured = json.loads(json.dumps(event_log.structured))
        
        # 对需要加密的字段进行加密
        if EncryptionConfig.should_encrypt():
            user_id = EncryptionConfig.TEST_USER_ID
            
            try:
                public_key_pem = self.db.get_user_public_key(user_id)
            except ValueError as e:
                raise RuntimeError(
                    f"获取用户公钥失败: {e}，请确保用户 {user_id} 已创建"
                )
            
            # 遍历需要加密的字段
            for field_path in EncryptionConfig.ENCRYPTED_FIELDS:
                value = self._get_nested_value(structured, field_path)
                if value is not None and not isinstance(value, str) or (isinstance(value, str) and not value.startswith("<encrypted>")):
                    # 加密字段值
                    try:
                        encrypted_value, encrypted_dek = self.encryption_service.encrypt_field_value(
                            event_id=event_log.event_id,
                            field_path=field_path,
                            value=str(value),
                            user_id=user_id,
                            public_key_pem=public_key_pem
                        )
                        
                        # 更新 structured 中的值
                        self._set_nested_value(structured, field_path, encrypted_value)
                        
                        # 存储 encrypted_dek 到数据库
                        self.db.insert_field_encryption_key(
                            event_id=event_log.event_id,
                            field_path=field_path,
                            user_id=user_id,
                            encrypted_dek=encrypted_dek
                        )
                    except Exception as e:
                        print(f"警告：加密字段 {field_path} 失败: {e}")
                        # 继续处理其他字段
        
        # 写入数据库
        encrypted_event_log = EventLog(
            event_id=event_log.event_id,
            segment_id=event_log.segment_id,
            start_time=event_log.start_time,
            end_time=event_log.end_time,
            event_type=event_log.event_type,  # 传递 event_type
            structured=structured,  # 已加密的 structured
            raw_text=event_log.raw_text
        )
        self.db.insert_event_log(encrypted_event_log)
        
        # 写入 JSONL 文件（用于调试）
        self._write_debug_log(event_log, structured)
    
    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """获取嵌套字段值（如 'person.clothing_color'）"""
        keys = path.split('.')
        value = data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value
    
    def _set_nested_value(self, data: Dict[str, Any], path: str, value: Any) -> None:
        """设置嵌套字段值（如 'person.clothing_color'）"""
        keys = path.split('.')
        target = data
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value
    
    def _write_debug_log(self, event_log: EventLog, encrypted_structured: Dict[str, Any]) -> None:
        """写入调试日志文件（JSONL 格式）"""
        log_file = self.debug_log_dir / "event_logs.jsonl"
        
        log_entry = {
            "event_id": event_log.event_id,
            "segment_id": event_log.segment_id,
            "start_time": event_log.start_time.isoformat(),
            "end_time": event_log.end_time.isoformat(),
            "event_type": event_log.event_type,  # 包含 event_type
            "structured": encrypted_structured,  # 已加密的结构化数据
            "raw_text": event_log.raw_text
        }
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

