"""认证相关功能"""

import bcrypt
import hashlib
import secrets
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

# 简单的内存 session 存储（生产环境应使用 Redis）
SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_SECRET = secrets.token_urlsafe(32)
SESSION_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def create_session(user_id: str, username: str, role: str) -> str:
    """创建 session，返回 session_id"""
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=SESSION_EXPIRE_HOURS)
    
    SESSIONS[session_id] = {
        'user_id': user_id,
        'username': username,
        'role': role,
        'created_at': datetime.now(),
        'expires_at': expires_at
    }
    
    return session_id


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """获取 session 信息"""
    if session_id not in SESSIONS:
        return None
    
    session = SESSIONS[session_id]
    
    # 检查是否过期
    if datetime.now() > session['expires_at']:
        del SESSIONS[session_id]
        return None
    
    return session


def delete_session(session_id: str) -> None:
    """删除 session"""
    if session_id in SESSIONS:
        del SESSIONS[session_id]


def calculate_public_key_fingerprint(public_key_pem: str) -> str:
    """计算公钥指纹（SHA256）"""
    # 移除 PEM 格式的头部和尾部，只保留密钥内容
    key_content = public_key_pem.replace('-----BEGIN PUBLIC KEY-----', '')
    key_content = key_content.replace('-----END PUBLIC KEY-----', '')
    key_content = key_content.replace('\n', '').strip()
    
    # 计算 SHA256
    hash_obj = hashlib.sha256(key_content.encode('utf-8'))
    return hash_obj.hexdigest()

