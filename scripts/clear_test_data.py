#!/usr/bin/env python3
"""清空测试数据脚本

用于有选择地清空视频理解和日终处理所生成的测试数据。
"""

import sys
import os
import json
import pymysql
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.database_config import DatabaseConfig

def get_db_connection():
    """获取数据库连接"""
    config = DatabaseConfig
    return pymysql.connect(
        host=config.HOST,
        port=config.PORT,
        user=config.USER,
        password=config.PASSWORD,
        database=config.DATABASE,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def clear_tables(tables):
    """清空指定的数据库表"""
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # 禁用外键检查以允许 TRUNCATE
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            for table in tables:
                try:
                    cursor.execute(f"TRUNCATE TABLE {table}")
                    print(f"  ✓ 数据库表 {table} 已清空")
                except Exception as e:
                    print(f"  ✗ 清空表 {table} 失败: {e}")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        connection.commit()
        connection.close()
        return True
    except Exception as e:
        print(f"  ✗ 数据库连接或操作失败: {e}")
        return False

def clear_files(filenames):
    """清空指定的文件内容"""
    log_dir = project_root / "logs_debug"
    for filename in filenames:
        file_path = log_dir / filename
        try:
            if file_path.exists():
                file_path.write_text('', encoding='utf-8')
                print(f"  ✓ 文件 {filename} 已清空")
            else:
                print(f"  - 文件 {filename} 不存在，跳过")
        except Exception as e:
            print(f"  ✗ 清空文件 {filename} 失败: {e}")

def main():
    print("=" * 60)
    print("清理测试数据")
    print("=" * 60)

    # 第一次提问
    ans1 = input("\n是否清空视频理解所生成的数据库表logs_raw、调试日志文件event_logs.jsonl、appearances.json？(y/N): ").strip().lower()
    if ans1 == 'y':
        print("\n正在清理视频理解数据...")
        clear_tables(['logs_raw'])
        clear_files(['event_logs.jsonl', 'appearances.json'])
    else:
        print("\n已跳过视频理解数据清理。")

    # 第二次提问
    ans2 = input("\n是否清空日终处理所生成的数据库表person_appearances、field_encryption_keys、logs_embedding？(y/N): ").strip().lower()
    if ans2 == 'y':
        print("\n正在清理日终处理数据...")
        # 注意顺序，或者在 clear_tables 中禁用外键检查
        clear_tables(['person_appearances', 'field_encryption_keys', 'logs_embedding'])
    else:
        print("\n已跳过日终处理数据清理。")

    print("\n" + "=" * 60)
    print("清理任务完成")
    print("=" * 60)

if __name__ == '__main__':
    main()
