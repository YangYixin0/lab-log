#!/usr/bin/env python3
"""数据库初始化脚本"""

import sys
import os
from pathlib import Path
from typing import Tuple
import pymysql
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

# 加载环境变量（.env 文件）
load_dotenv()

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.database_config import DatabaseConfig
from storage.seekdb_client import SeekDBClient


def execute_sql_file(file_path: Path, connection):
    """执行 SQL 文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # 分割 SQL 语句（按分号）
    # 过滤掉纯注释行，但保留包含 SQL 语句的行（即使有注释）
    statements = []
    for s in sql_content.split(';'):
        s = s.strip()
        if not s:
            continue
        # 移除行内注释（-- 开头的行），但保留 SQL 语句
        lines = [line.strip() for line in s.split('\n') if line.strip() and not line.strip().startswith('--')]
        if lines:
            # 重新组合非注释行
            clean_stmt = ' '.join(lines)
            if clean_stmt:
                statements.append(clean_stmt)
    
    # 从配置中获取数据库名（更可靠）
    database_name = DatabaseConfig.DATABASE
    
    # 先执行 CREATE DATABASE（如果存在）
    create_db_stmt = None
    use_stmt = None
    other_statements = []
    
    for statement in statements:
        if statement.upper().startswith('CREATE DATABASE'):
            create_db_stmt = statement
        elif statement.upper().startswith('USE '):
            use_stmt = statement
        else:
            other_statements.append(statement)
    
    with connection.cursor() as cursor:
        # 1. 先创建数据库
        if create_db_stmt:
            try:
                cursor.execute(create_db_stmt)
                connection.commit()  # 提交以确保数据库立即可用
                print(f"  数据库 '{database_name}' 创建成功（或已存在）")
            except Exception as e:
                print(f"执行 SQL 失败: {create_db_stmt[:100]}...")
                print(f"错误: {e}")
                raise
        else:
            # 如果没有 CREATE DATABASE 语句，直接创建
            try:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                connection.commit()
                print(f"  数据库 '{database_name}' 创建成功（或已存在）")
            except Exception as e:
                print(f"创建数据库失败: {e}")
                raise
        
        # 2. 切换到数据库（需要稍等片刻让数据库生效）
        import time
        time.sleep(0.1)  # 短暂等待确保数据库创建完成
        try:
            connection.select_db(database_name)
            print(f"  已切换到数据库 '{database_name}'")
        except Exception as e:
            print(f"切换数据库失败: {e}")
            print(f"提示: 请确保数据库 '{database_name}' 已创建")
            raise
        
        # 3. 执行其他语句（CREATE TABLE 等）
        for statement in other_statements:
            try:
                cursor.execute(statement)
            except Exception as e:
                print(f"执行 SQL 失败: {statement[:100]}...")
                print(f"错误: {e}")
                raise
    
    connection.commit()


def generate_rsa_keypair() -> Tuple[str, str]:
    """生成 RSA 密钥对（用于测试用户）"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    
    public_key = private_key.public_key()
    
    # 序列化为 PEM 格式
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')
    
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')
    
    return private_key_pem, public_key_pem


def drop_database_and_tables(connection, database_name: str):
    """删除数据库（如果存在）"""
    try:
        with connection.cursor() as cursor:
            # 先删除数据库（这会自动删除所有表）
            cursor.execute(f"DROP DATABASE IF EXISTS {database_name}")
            connection.commit()
            print(f"  已删除数据库 '{database_name}'（如果存在）")
    except Exception as e:
        print(f"  删除数据库失败: {e}")
        raise


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='初始化数据库')
    parser.add_argument('--drop-first', action='store_true', 
                       help='先删除数据库再重新创建（清空所有数据）')
    args = parser.parse_args()
    
    print("开始初始化数据库...")
    
    database_name = DatabaseConfig.DATABASE
    
    # 0. 如果指定了 --drop-first，先删除数据库
    if args.drop_first:
        print("步骤 0/3: 删除现有数据库...")
        try:
            # 连接到 MySQL（不指定数据库）
            conn = pymysql.connect(
                host=DatabaseConfig.HOST,
                port=DatabaseConfig.PORT,
                user=DatabaseConfig.USER,
                password=DatabaseConfig.PASSWORD,
                charset='utf8mb4'
            )
            drop_database_and_tables(conn, database_name)
            conn.close()
        except Exception as e:
            print(f"  删除数据库失败: {e}")
            sys.exit(1)
    
    # 1. 执行 schema.sql
    print("步骤 1/3: 创建数据库和表...")
    schema_file = project_root / 'storage' / 'schema.sql'
    if not schema_file.exists():
        print(f"错误: Schema 文件不存在: {schema_file}")
        sys.exit(1)
    
    try:
        # 连接到 MySQL（不指定数据库，用于创建数据库）
        conn = pymysql.connect(
            host=DatabaseConfig.HOST,
            port=DatabaseConfig.PORT,
            user=DatabaseConfig.USER,
            password=DatabaseConfig.PASSWORD,
            charset='utf8mb4'
        )
        
        execute_sql_file(schema_file, conn)
        conn.close()
        print("  数据库和表创建成功")
    except Exception as e:
        print(f"  创建数据库和表失败: {e}")
        sys.exit(1)
    
    # 2. 创建测试用户（admin）
    print("步骤 2/3: 创建测试用户（admin）...")
    
    # 检查用户是否已存在
    user_exists = False
    try:
        with SeekDBClient() as db:
            existing_user = db.get_user_by_id('admin')
            if existing_user:
                user_exists = True
    except:
        pass
    
    if user_exists and not args.drop_first:
        print("  测试用户已存在，跳过创建")
        keys_dir = project_root / 'scripts' / 'test_keys'
        private_key_file = keys_dir / 'admin_private_key.pem'
    else:
        private_key_pem, public_key_pem = generate_rsa_keypair()
        
        # 保存私钥到文件（仅用于测试）
        keys_dir = project_root / 'scripts' / 'test_keys'
        keys_dir.mkdir(exist_ok=True)
        private_key_file = keys_dir / 'admin_private_key.pem'
        with open(private_key_file, 'w') as f:
            f.write(private_key_pem)
        print(f"  测试用户私钥已保存到: {private_key_file}")
        print("  警告: 请妥善保管私钥文件，不要提交到版本控制系统！")
        
        try:
            from web_api.auth import hash_password
            # 为 admin 用户设置默认密码 "admin"（仅用于测试）
            admin_password_hash = hash_password('admin')
            
            with SeekDBClient() as db:
                db.create_user(
                    user_id='admin',
                    username='admin',
                    public_key_pem=public_key_pem,
                    password_hash=admin_password_hash,
                    role='admin'
                )
            print("  测试用户创建成功（用户名: admin, 密码: admin, 角色: admin）")
        except Exception as e:
            print(f"  创建测试用户失败: {e}")
            sys.exit(1)
    
    # 3. 验证
    print("步骤 3/3: 验证数据库...")
    try:
        with SeekDBClient() as db:
            public_key = db.get_user_public_key('admin')
            if public_key:
                print("  数据库初始化成功！")
            else:
                print("  警告: 无法获取测试用户公钥")
    except Exception as e:
        print(f"  验证失败: {e}")
        sys.exit(1)
    
    print("\n数据库初始化完成！")
    print(f"测试用户 ID: admin")
    print(f"私钥文件: {private_key_file}")


if __name__ == '__main__':
    main()

