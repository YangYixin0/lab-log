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
                                 event_type, structured, raw_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
                        event_log.event_type,
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
    
    def create_user(self, user_id: str, username: str, public_key_pem: str, 
                    password_hash: Optional[str] = None, role: str = 'user') -> None:
        """创建用户"""
        self._ensure_connected()
        
        sql = """
            INSERT INTO users (user_id, username, public_key_pem, password_hash, role)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE username = VALUES(username), 
                                   public_key_pem = VALUES(public_key_pem),
                                   password_hash = VALUES(password_hash),
                                   role = VALUES(role)
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (user_id, username, public_key_pem, password_hash, role))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise RuntimeError(f"创建用户失败: {e}")
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """根据用户名查询用户"""
        self._ensure_connected()
        
        sql = """
            SELECT user_id, username, public_key_pem, password_hash, role, created_at
            FROM users
            WHERE username = %s
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (username,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            raise RuntimeError(f"查询用户失败: {e}")
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """根据用户 ID 查询用户"""
        self._ensure_connected()
        
        sql = """
            SELECT user_id, username, public_key_pem, password_hash, role, created_at
            FROM users
            WHERE user_id = %s
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (user_id,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            raise RuntimeError(f"查询用户失败: {e}")
    
    def update_user_role(self, user_id: str, role: str) -> None:
        """更新用户角色（仅 admin 可用）"""
        self._ensure_connected()
        
        sql = """
            UPDATE users
            SET role = %s
            WHERE user_id = %s
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (role, user_id))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise RuntimeError(f"更新用户角色失败: {e}")
    
    def get_table_names(self) -> List[str]:
        """获取所有表名"""
        self._ensure_connected()
        
        sql = """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (self.config.DATABASE,))
                results = cursor.fetchall()
                return [row['TABLE_NAME'] for row in results]
        except Exception as e:
            raise RuntimeError(f"获取表名失败: {e}")
    
    def vector_search(self, query_vector: List[float], limit: int = 10) -> List[Dict[str, Any]]:
        """
        执行向量搜索（使用余弦距离）
        
        Args:
            query_vector: 查询向量（1024 维）
            limit: 返回结果数量
            
        Returns:
            搜索结果列表，每个结果包含：
            - chunk_id: 分块 ID
            - chunk_text: 分块文本
            - related_event_ids: 关联的事件 ID（JSON 字符串）
            - start_time: 开始时间
            - end_time: 结束时间
            - distance: 余弦距离
        """
        self._ensure_connected()
        
        # 将向量转换为 JSON 字符串（需要转义单引号）
        vector_json = json.dumps(query_vector)
        # 转义单引号以防止 SQL 注入
        vector_json_escaped = vector_json.replace("'", "''")
        
        sql = f"""
            SELECT 
                chunk_id,
                chunk_text,
                related_event_ids,
                start_time,
                end_time,
                cosine_distance(embedding, '{vector_json_escaped}') AS distance
            FROM logs_embedding
            ORDER BY distance
            LIMIT %s
        """
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (limit,))
                results = cursor.fetchall()
                
                # 转换为字典列表
                search_results = []
                for row in results:
                    search_results.append({
                        'chunk_id': row['chunk_id'],
                        'chunk_text': row['chunk_text'],
                        'related_event_ids': row['related_event_ids'],
                        'start_time': str(row['start_time']) if row['start_time'] else None,
                        'end_time': str(row['end_time']) if row['end_time'] else None,
                        'distance': float(row['distance']) if row['distance'] is not None else None
                    })
                
                return search_results
        except Exception as e:
            raise RuntimeError(f"向量搜索失败: {e}")
    
    def get_table_data(self, table_name: str, page: int = 1, limit: int = 50) -> Dict[str, Any]:
        """获取表数据（支持分页）"""
        self._ensure_connected()
        
        # 验证表名（防止 SQL 注入）
        allowed_tables = ['users', 'logs_raw', 'logs_embedding', 'tickets', 'field_encryption_keys']
        if table_name not in allowed_tables:
            raise ValueError(f"不允许访问表: {table_name}")
        
        offset = (page - 1) * limit
        
        # 获取表结构
        sql_structure = """
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """
        
        # 获取数据（按created_at降序排序，新数据在前）
        # 检查表是否有created_at字段
        sql_data = f"SELECT * FROM `{table_name}`"
        has_created_at = False
        
        # 先检查是否有created_at字段
        try:
            check_column_sql = """
                SELECT COUNT(*) as cnt FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = 'created_at'
            """
            with self.connection.cursor() as check_cursor:
                check_cursor.execute(check_column_sql, (self.config.DATABASE, table_name))
                result = check_cursor.fetchone()
                has_created_at = result['cnt'] > 0 if result else False
        except Exception:
            # 如果检查失败，不添加排序
            has_created_at = False
        
        if has_created_at:
            # 按created_at降序，相同时间按event_id降序（如果表有event_id字段）
            # 检查是否有event_id字段
            has_event_id = False
            try:
                check_event_id_sql = """
                    SELECT COUNT(*) as cnt FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = 'event_id'
                """
                with self.connection.cursor() as check_cursor:
                    check_cursor.execute(check_event_id_sql, (self.config.DATABASE, table_name))
                    result = check_cursor.fetchone()
                    has_event_id = result['cnt'] > 0 if result else False
            except Exception:
                has_event_id = False
            
            if has_event_id:
                sql_data += " ORDER BY created_at DESC, event_id DESC"
            else:
                sql_data += " ORDER BY created_at DESC"
        
        sql_data += " LIMIT %s OFFSET %s"
        
        # 获取总数
        sql_count = f"SELECT COUNT(*) as total FROM `{table_name}`"
        
        try:
            with self.connection.cursor() as cursor:
                # 获取表结构
                cursor.execute(sql_structure, (self.config.DATABASE, table_name))
                columns = cursor.fetchall()
                
                # 获取总数
                cursor.execute(sql_count)
                total_result = cursor.fetchone()
                total = total_result['total'] if total_result else 0
                
                # 获取数据
                cursor.execute(sql_data, (limit, offset))
                data = cursor.fetchall()
                
                return {
                    'columns': [dict(col) for col in columns],
                    'data': [dict(row) for row in data],
                    'total': total,
                    'page': page,
                    'limit': limit,
                    'total_pages': (total + limit - 1) // limit
                }
        except Exception as e:
            raise RuntimeError(f"获取表数据失败: {e}")
    
    def close(self):
        """关闭连接"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

