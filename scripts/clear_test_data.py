#!/usr/bin/env python3
"""清空测试数据脚本

用于清空测试后的数据库数据和调试日志文件。
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import pymysql

# 加载环境变量
load_dotenv()

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.database_config import DatabaseConfig


def clear_database_tables():
    """清空数据库中的测试数据表"""
    config = DatabaseConfig
    
    try:
        # 连接数据库
        connection = pymysql.connect(
            host=config.HOST,
            port=config.PORT,
            user=config.USER,
            password=config.PASSWORD,
            database=config.DATABASE,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        print(f"已连接到数据库: {config.HOST}:{config.PORT}/{config.DATABASE}")
        
        with connection.cursor() as cursor:
            # 需要清空的表（按依赖关系顺序）
            tables_to_clear = [
                'field_encryption_keys',  # 依赖 logs_raw，先清空
                'logs_embedding',         # 独立表
                'logs_raw',               # 核心日志表
            ]
            
            cleared_counts = {}
            
            for table in tables_to_clear:
                try:
                    # 先查询记录数
                    cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                    count_result = cursor.fetchone()
                    count = count_result['count'] if count_result else 0
                    
                    if count > 0:
                        # 清空表
                        cursor.execute(f"TRUNCATE TABLE {table}")
                        cleared_counts[table] = count
                        print(f"  ✓ 清空表 {table}: {count} 条记录")
                    else:
                        print(f"  - 表 {table}: 无数据")
                        cleared_counts[table] = 0
                        
                except Exception as e:
                    print(f"  ✗ 清空表 {table} 失败: {e}")
                    continue
            
            # 提交事务
            connection.commit()
            
            # 统计总清空记录数
            total_cleared = sum(cleared_counts.values())
            if total_cleared > 0:
                print(f"\n数据库清空完成，共清空 {total_cleared} 条记录")
            else:
                print("\n数据库已为空，无需清空")
            
            return True
            
    except pymysql.Error as e:
        print(f"数据库操作失败: {e}")
        return False
    except Exception as e:
        print(f"连接数据库失败: {e}")
        return False
    finally:
        if 'connection' in locals():
            connection.close()


def clear_debug_log_file():
    """清空或删除调试日志文件"""
    log_dir = project_root / "logs_debug"
    log_file = log_dir / "event_logs.jsonl"
    
    try:
        # 确保目录存在
        log_dir.mkdir(exist_ok=True)
        
        if log_file.exists():
            # 获取文件大小
            file_size = log_file.stat().st_size
            
            # 清空文件（保留文件，但内容为空）
            log_file.write_text('', encoding='utf-8')
            print(f"  ✓ 清空调试日志文件: {log_file}")
            print(f"    原文件大小: {file_size} 字节")
            return True
        else:
            print(f"  - 调试日志文件不存在: {log_file}")
            return True
            
    except Exception as e:
        print(f"  ✗ 清空调试日志文件失败: {e}")
        return False


def main():
    """主函数"""
    print("=" * 60)
    print("清空测试数据")
    print("=" * 60)
    print()
    
    # 确认操作
    print("此操作将清空以下数据：")
    print("  1. 数据库表: logs_raw, logs_embedding, field_encryption_keys")
    print("  2. 调试日志文件: logs_debug/event_logs.jsonl")
    print()
    
    # 可选：添加交互式确认（如果需要，取消下面的注释）
    # response = input("确认清空？(yes/no): ").strip().lower()
    # if response not in ['yes', 'y']:
    #     print("操作已取消")
    #     return
    
    print("开始清空...")
    print()
    
    # 清空数据库
    print("步骤 1/2: 清空数据库表...")
    db_success = clear_database_tables()
    print()
    
    # 清空日志文件
    print("步骤 2/2: 清空调试日志文件...")
    log_success = clear_debug_log_file()
    print()
    
    # 总结
    print("=" * 60)
    if db_success and log_success:
        print("✓ 所有测试数据已清空")
    else:
        print("✗ 部分操作失败，请检查上述错误信息")
    print("=" * 60)


if __name__ == '__main__':
    main()

