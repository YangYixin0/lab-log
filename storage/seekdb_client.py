"""SeekDB 客户端封装"""

import json
from typing import Optional, List, Dict, Any
import pymysql
from pymysql.cursors import DictCursor

from config.database_config import DatabaseConfig
from storage.models import EventLog


class SeekDBClient:
    """SeekDB 客户端"""
    
    def __init__(self, config: Optional[DatabaseConfig] = None):
        """初始化客户端"""
        if config is None:
            config = DatabaseConfig()
        self.config = config
        self.connection = None
        self._connect()
    
    def _connect(self):
        """建立数据库连接"""
        try:
            self.connection = pymysql.connect(
                host=self.config.HOST,
                port=self.config.PORT,
                database=self.config.DATABASE,
                user=self.config.USER,
                password=self.config.PASSWORD,
                charset='utf8mb4',
                cursorclass=DictCursor,
                autocommit=False
            )
        except Exception as e:
            raise ConnectionError(f"无法连接到 SeekDB: {e}")
    
    def _ensure_connected(self):
        """确保连接可用"""
        if self.connection is None:
            self._connect()
        try:
            self.connection.ping(reconnect=True)
        except:
            self._connect()
    
    def insert_event_log(self, event_log: EventLog) -> None:
        """插入事件日志（包含加密后的 structured 字段）"""
        self._ensure_connected()
        
        sql = """
            INSERT INTO logs_raw (event_id, segment_id, start_time, end_time, 
                                 encrypted_structured, raw_text)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        try:
            with self.connection.cursor() as cursor:
                # 将 structured dict 转换为 JSON 字符串
                structured_json = json.dumps(event_log.structured, ensure_ascii=False)
                cursor.execute(
                    sql,
                    (
                        event_log.event_id,
                        event_log.segment_id,
                        event_log.start_time,
                        event_log.end_time,
                        structured_json,
                        event_log.raw_text
                    )
                )
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise RuntimeError(f"插入事件日志失败: {e}")
    
    def get_user_public_key(self, user_id: str) -> str:
        """获取用户公钥（PEM 格式）"""
        self._ensure_connected()
        
        sql = "SELECT public_key_pem FROM users WHERE user_id = %s"
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (user_id,))
                result = cursor.fetchone()
                if result is None:
                    raise ValueError(f"用户 {user_id} 不存在")
                return result['public_key_pem']
        except Exception as e:
            raise RuntimeError(f"获取用户公钥失败: {e}")
    
    def insert_field_encryption_key(self, event_id: str, field_path: str,
                                   user_id: str, encrypted_dek: str) -> None:
        """插入字段加密密钥（DEK）"""
        self._ensure_connected()
        
        sql = """
            INSERT INTO field_encryption_keys (event_id, field_path, user_id, encrypted_dek)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE encrypted_dek = VALUES(encrypted_dek)
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (event_id, field_path, user_id, encrypted_dek))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise RuntimeError(f"插入字段加密密钥失败: {e}")
    
    def get_field_encryption_key(self, event_id: str, field_path: str,
                                 user_id: str) -> Optional[str]:
        """获取字段加密密钥（DEK）"""
        self._ensure_connected()
        
        sql = """
            SELECT encrypted_dek FROM field_encryption_keys
            WHERE event_id = %s AND field_path = %s AND user_id = %s
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (event_id, field_path, user_id))
                result = cursor.fetchone()
                if result is None:
                    return None
                return result['encrypted_dek']
        except Exception as e:
            raise RuntimeError(f"获取字段加密密钥失败: {e}")
    
    def query_event_logs(self, segment_id: Optional[str] = None,
                        start_time: Optional[str] = None,
                        end_time: Optional[str] = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
        """查询事件日志"""
        self._ensure_connected()
        
        sql = "SELECT * FROM logs_raw WHERE 1=1"
        params = []
        
        if segment_id:
            sql += " AND segment_id = %s"
            params.append(segment_id)
        if start_time:
            sql += " AND start_time >= %s"
            params.append(start_time)
        if end_time:
            sql += " AND end_time <= %s"
            params.append(end_time)
        
        sql += " ORDER BY start_time DESC LIMIT %s"
        params.append(limit)
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                results = cursor.fetchall()
                return list(results)
        except Exception as e:
            raise RuntimeError(f"查询事件日志失败: {e}")
    
    def insert_log_chunk(self, chunk_id: str, chunk_text: str,
                        related_event_ids: List[str], embedding: List[float],
                        start_time: str, end_time: str) -> None:
        """插入日志分块和向量嵌入"""
        self._ensure_connected()
        
        sql = """
            INSERT INTO logs_embedding (chunk_id, chunk_text, related_event_ids,
                                       embedding, start_time, end_time)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        try:
            with self.connection.cursor() as cursor:
                # 将 event_ids 列表转换为 JSON
                event_ids_json = json.dumps(related_event_ids, ensure_ascii=False)
                # 将 embedding 向量转换为 JSON 数组字符串（SeekDB 需要）
                embedding_json = json.dumps(embedding, ensure_ascii=False)
                
                cursor.execute(
                    sql,
                    (
                        chunk_id,
                        chunk_text,
                        event_ids_json,
                        embedding_json,  # SeekDB 会自动转换为 VECTOR 类型
                        start_time,
                        end_time
                    )
                )
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise RuntimeError(f"插入日志分块失败: {e}")
    
    def create_user(self, user_id: str, username: str, public_key_pem: str) -> None:
        """创建用户"""
        self._ensure_connected()
        
        sql = """
            INSERT INTO users (user_id, username, public_key_pem)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE username = VALUES(username), 
                                   public_key_pem = VALUES(public_key_pem)
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (user_id, username, public_key_pem))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise RuntimeError(f"创建用户失败: {e}")
    
    def close(self):
        """关闭连接"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

