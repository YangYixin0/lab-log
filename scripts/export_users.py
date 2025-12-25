#!/usr/bin/env python3
"""导出用户信息表到文件"""

import sys
import json
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from storage.seekdb_client import SeekDBClient

# 加载环境变量
load_dotenv()


def export_users_table():
    """导出用户表数据到 JSON 文件"""
    print("开始导出用户信息表...")
    
    db_client = None
    try:
        # 创建数据库客户端
        db_client = SeekDBClient()
        
        # 查询所有用户
        sql = """
            SELECT user_id, username, public_key_pem, password_hash, role, created_at
            FROM users
            ORDER BY created_at
        """
        
        users = []
        with db_client.connection.cursor() as cursor:
            cursor.execute(sql)
            results = cursor.fetchall()
            for row in results:
                users.append({
                    'user_id': row['user_id'],
                    'username': row['username'],
                    'public_key_pem': row['public_key_pem'],
                    'password_hash': row['password_hash'],
                    'role': row['role'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None
                })
        
        # 生成文件名（带时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = project_root / f"users_export_{timestamp}.json"
        
        # 保存为 JSON 文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        
        print(f"✓ 成功导出 {len(users)} 个用户")
        print(f"✓ 文件已保存到: {output_file}")
        print(f"\n文件内容预览（前3个用户）:")
        for i, user in enumerate(users[:3], 1):
            print(f"  {i}. {user['username']} ({user['role']}) - {user['user_id']}")
        if len(users) > 3:
            print(f"  ... 还有 {len(users) - 3} 个用户")
        
        return output_file
        
    except Exception as e:
        print(f"✗ 导出失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if db_client:
            db_client.close()


if __name__ == "__main__":
    export_users_table()

