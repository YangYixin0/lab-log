"""日志写入器（写入数据库和 JSONL 文件）"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from storage.seekdb_client import SeekDBClient
from storage.models import EventLog


class LogWriter:
    """日志写入器（简化版本，不加密）"""
    
    def __init__(
        self,
        db_client: SeekDBClient,
        debug_log_dir: str = "logs_debug",
        enable_encryption: bool = False
    ):
        """
        初始化写入器
        
        Args:
            db_client: 数据库客户端
            debug_log_dir: 调试日志目录
            enable_encryption: 是否启用加密（默认关闭，兼容旧版）
        """
        self.db = db_client
        self.debug_log_dir = Path(debug_log_dir)
        self.debug_log_dir.mkdir(parents=True, exist_ok=True)
        self.enable_encryption = enable_encryption
        
        # 懒加载加密服务（仅在需要时导入）
        self._encryption_service = None
    
    def write_event_log(self, event_log: EventLog) -> None:
        """
        写入事件日志（写入数据库和 JSONL 文件）
        
        Args:
            event_log: 事件日志
        """
        # 深拷贝 structured 避免修改原数据
        structured = json.loads(json.dumps(event_log.structured))
        
        # 如果启用加密，执行加密逻辑（兼容旧版）
        if self.enable_encryption:
            structured = self._encrypt_fields(event_log, structured)
        
        # 写入数据库
        db_event_log = EventLog(
            event_id=event_log.event_id,
            segment_id=event_log.segment_id,
            start_time=event_log.start_time,
            end_time=event_log.end_time,
            event_type=event_log.event_type,
            structured=structured,
            raw_text=event_log.raw_text
        )
        self.db.insert_event_log(db_event_log)
        
        # 写入 JSONL 文件（用于调试）
        self._write_debug_log(event_log, structured)

    def write_emergency_log(self, emergency: Any) -> None:
        """写入紧急情况日志"""
        self.db.insert_emergency_log(emergency)
        self._write_emergency_debug_log(emergency)

    def _write_emergency_debug_log(self, emergency: Any) -> None:
        """写入紧急情况调试日志"""
        log_file = self.debug_log_dir / "emergencies.jsonl"
        log_entry = {
            "emergency_id": emergency.emergency_id,
            "description": emergency.description,
            "status": emergency.status,
            "start_time": emergency.start_time.isoformat(),
            "end_time": emergency.end_time.isoformat(),
            "segment_id": emergency.segment_id,
            "created_at": datetime.now().isoformat()
        }
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def _encrypt_fields(self, event_log: EventLog, structured: Dict[str, Any]) -> Dict[str, Any]:
        """
        加密指定字段（兼容旧版）
        
        Args:
            event_log: 事件日志
            structured: 结构化数据
        
        Returns:
            加密后的结构化数据
        """
        try:
            from config.encryption_config import EncryptionConfig
            from log_writer.encryption_service import FieldEncryptionService
            
            if not EncryptionConfig.should_encrypt():
                return structured
            
            if self._encryption_service is None:
                self._encryption_service = FieldEncryptionService()
            
            user_id = EncryptionConfig.TEST_USER_ID
            
            try:
                public_key_pem = self.db.get_user_public_key(user_id)
            except ValueError as e:
                print(f"警告：获取用户公钥失败: {e}")
                return structured
            
            # 遍历需要加密的字段
            for field_path in EncryptionConfig.ENCRYPTED_FIELDS:
                value = self._get_nested_value(structured, field_path)
                if value is not None and not (isinstance(value, str) and value.startswith("<encrypted>")):
                    try:
                        encrypted_value, encrypted_dek = self._encryption_service.encrypt_field_value(
                            event_id=event_log.event_id,
                            field_path=field_path,
                            value=str(value),
                            user_id=user_id,
                            public_key_pem=public_key_pem
                        )
                        
                        self._set_nested_value(structured, field_path, encrypted_value)
                        
                        # 提取事件发生的日期
                        event_date = event_log.start_time.strftime('%Y-%m-%d')
                        
                        self.db.insert_field_encryption_key(
                            ref_id=event_log.event_id,
                            ref_date=event_date,
                            field_path=field_path,
                            user_id=user_id,
                            encrypted_dek=encrypted_dek
                        )
                    except Exception as e:
                        print(f"警告：加密字段 {field_path} 失败: {e}")
        except ImportError as e:
            print(f"警告：加密模块不可用: {e}")
        
        return structured
    
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
    
    def _write_debug_log(self, event_log: EventLog, structured: Dict[str, Any]) -> None:
        """写入调试日志文件（JSONL 格式）"""
        log_file = self.debug_log_dir / "event_logs.jsonl"
        
        log_entry = {
            "event_id": event_log.event_id,
            "segment_id": event_log.segment_id,
            "start_time": event_log.start_time.isoformat(),
            "end_time": event_log.end_time.isoformat(),
            "event_type": event_log.event_type,
            "structured": structured,
            "raw_text": event_log.raw_text
        }
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')


class SimpleLogWriter:
    """简化日志写入器（不加密，用于动态上下文模式）"""
    
    def __init__(
        self,
        db_client: SeekDBClient,
        debug_log_dir: str = "logs_debug"
    ):
        """
        初始化写入器
        
        Args:
            db_client: 数据库客户端
            debug_log_dir: 调试日志目录
        """
        self.db = db_client
        self.debug_log_dir = Path(debug_log_dir)
        self.debug_log_dir.mkdir(parents=True, exist_ok=True)
    
    def write_event_log(self, event_log: EventLog) -> None:
        """
        写入事件日志（直接写入，不加密）
        
        Args:
            event_log: 事件日志
        """
        # 写入数据库
        self.db.insert_event_log(event_log)
        
        # 写入 JSONL 文件（用于调试）
        self._write_debug_log(event_log)

    def write_emergency_log(self, emergency: Any) -> None:
        """写入紧急情况日志"""
        self.db.insert_emergency_log(emergency)
        self._write_emergency_debug_log(emergency)

    def _write_emergency_debug_log(self, emergency: Any) -> None:
        """写入紧急情况调试日志"""
        log_file = self.debug_log_dir / "emergencies.jsonl"
        log_entry = {
            "emergency_id": emergency.emergency_id,
            "description": emergency.description,
            "status": emergency.status,
            "start_time": emergency.start_time.isoformat(),
            "end_time": emergency.end_time.isoformat(),
            "segment_id": emergency.segment_id,
            "created_at": datetime.now().isoformat()
        }
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def _write_debug_log(self, event_log: EventLog) -> None:
        """写入调试日志文件（JSONL 格式）"""
        log_file = self.debug_log_dir / "event_logs.jsonl"
        
        log_entry = {
            "event_id": event_log.event_id,
            "segment_id": event_log.segment_id,
            "start_time": event_log.start_time.isoformat(),
            "end_time": event_log.end_time.isoformat(),
            "event_type": event_log.event_type,
            "structured": event_log.structured,
            "raw_text": event_log.raw_text
        }
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
