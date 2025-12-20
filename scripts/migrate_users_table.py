#!/usr/bin/env python3
"""迁移 users 表，添加 role 和 password_hash 字段"""

import sys
from pathlib import Path
import pymysql
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.database_config import DatabaseConfig


def migrate_users_table():
    """迁移 users 表"""
    print("开始迁移 users 表...")
    
    try:
        conn = pymysql.connect(
            host=DatabaseConfig.HOST,
            port=DatabaseConfig.PORT,
            database=DatabaseConfig.DATABASE,
            user=DatabaseConfig.USER,
            password=DatabaseConfig.PASSWORD,
            charset='utf8mb4'
        )
        
        with conn.cursor() as cursor:
            # 检查字段是否存在
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = %s 
                AND TABLE_NAME = 'users' 
                AND COLUMN_NAME IN ('role', 'password_hash')
            """, (DatabaseConfig.DATABASE,))
            
            existing_columns = {row[0] for row in cursor.fetchall()}
            
            # 添加 role 字段（如果不存在）
            if 'role' not in existing_columns:
                print("  添加 role 字段...")
                cursor.execute("""
                    ALTER TABLE users 
                    ADD COLUMN role ENUM('admin', 'user') DEFAULT 'user' COMMENT '用户角色'
                """)
                print("  ✓ role 字段已添加")
            else:
                print("  ✓ role 字段已存在")
            
            # 添加 password_hash 字段（如果不存在）
            if 'password_hash' not in existing_columns:
                print("  添加 password_hash 字段...")
                cursor.execute("""
                    ALTER TABLE users 
                    ADD COLUMN password_hash VARCHAR(255) COMMENT 'bcrypt 哈希密码（可选，支持公钥登录的用户可为 NULL）'
                """)
                print("  ✓ password_hash 字段已添加")
            else:
                print("  ✓ password_hash 字段已存在")
            
            # 检查并添加索引
            cursor.execute("""
                SELECT INDEX_NAME 
                FROM INFORMATION_SCHEMA.STATISTICS 
                WHERE TABLE_SCHEMA = %s 
                AND TABLE_NAME = 'users' 
                AND INDEX_NAME = 'idx_role'
            """, (DatabaseConfig.DATABASE,))
            
            if not cursor.fetchone():
                print("  添加 idx_role 索引...")
                cursor.execute("ALTER TABLE users ADD INDEX idx_role (role)")
                print("  ✓ idx_role 索引已添加")
            else:
                print("  ✓ idx_role 索引已存在")
            
            # 更新现有 admin 用户的 role
            cursor.execute("SELECT COUNT(*) FROM users WHERE user_id = 'admin' AND role != 'admin'")
            if cursor.fetchone()[0] > 0:
                print("  更新 admin 用户的 role...")
                cursor.execute("UPDATE users SET role = 'admin' WHERE user_id = 'admin'")
                print("  ✓ admin 用户 role 已更新")
            
            conn.commit()
            print("\n迁移完成！")
            
    except Exception as e:
        print(f"迁移失败: {e}")
        if conn:
            conn.rollback()
        sys.exit(1)
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    migrate_users_table()

