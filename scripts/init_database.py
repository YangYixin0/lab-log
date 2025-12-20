#!/usr/bin/env python3
"""数据库初始化脚本"""

import sys
import os
from pathlib import Path
from typing import Tuple
import pymysql
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.database_config import DatabaseConfig
from storage.seekdb_client import SeekDBClient


def execute_sql_file(file_path: Path, connection):
    """执行 SQL 文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # 分割 SQL 语句（按分号和换行）
    statements = [s.strip() for s in sql_content.split(';') if s.strip() and not s.strip().startswith('--')]
    
    with connection.cursor() as cursor:
        for statement in statements:
            if statement:
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


def main():
    print("开始初始化数据库...")
    
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
        with SeekDBClient() as db:
            db.create_user(
                user_id='admin',
                username='admin',
                public_key_pem=public_key_pem
            )
        print("  测试用户创建成功")
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

