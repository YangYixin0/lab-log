"""FastAPI 依赖注入"""

from typing import Optional
from fastapi import Cookie, HTTPException, status
from storage.seekdb_client import SeekDBClient
from api.auth import get_session


def get_db() -> SeekDBClient:
    """获取数据库客户端"""
    return SeekDBClient()


def get_current_user(
    session_id: Optional[str] = Cookie(None, alias="session_id")
) -> dict:
    """获取当前登录用户"""
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录"
        )
    
    session = get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session 已过期或无效"
        )
    
    return {
        'user_id': session['user_id'],
        'username': session['username'],
        'role': session['role']
    }
