"""认证路由"""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from web_api.models.schemas import UserRegister, UserLogin, UserResponse
from web_api.auth import hash_password, verify_password, create_session, delete_session
from web_api.dependencies import get_db
from storage.seekdb_client import SeekDBClient

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
def register(user_data: UserRegister, db: SeekDBClient = Depends(get_db)):
    """用户注册"""
    # 检查用户名是否已存在
    existing_user = db.get_user_by_username(user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 密码是必填项
    if not user_data.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码是必填项"
        )
    
    # 公钥也是必填项（注册时自动生成）
    if not user_data.public_key_pem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="公钥是必填项"
        )
    
    # 生成 user_id
    user_id = str(uuid.uuid4())
    
    # 哈希密码（密码是必填项）
    password_hash = hash_password(user_data.password)
    
    # 使用提供的公钥（公钥是必填项）
    public_key_pem = user_data.public_key_pem
    
    # 创建用户（默认 role='user'）
    try:
        db.create_user(
            user_id=user_id,
            username=user_data.username,
            public_key_pem=public_key_pem,
            password_hash=password_hash,
            role='user'
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建用户失败: {str(e)}"
        )
    
    return UserResponse(
        user_id=user_id,
        username=user_data.username,
        role='user'
    )


@router.post("/login", response_model=UserResponse)
def login(
    user_data: UserLogin,
    response: Response,
    db: SeekDBClient = Depends(get_db)
):
    """用户登录"""
    # 查找用户
    user = db.get_user_by_username(user_data.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 验证密码（密码登录是唯一方式）
    if not user['password_hash']:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该用户未设置密码"
        )
    
    authenticated = verify_password(user_data.password, user['password_hash'])
    
    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 创建 session
    session_id = create_session(
        user_id=user['user_id'],
        username=user['username'],
        role=user['role']
    )
    
    # 设置 Cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=86400  # 24 小时
    )
    
    return UserResponse(
        user_id=user['user_id'],
        username=user['username'],
        role=user['role']
    )


@router.post("/logout")
def logout(
    response: Response,
    current_user: dict = Depends(lambda: None)  # 简化，实际应该从 cookie 获取
):
    """登出"""
    # 删除 Cookie
    response.delete_cookie(key="session_id")
    return {"message": "已登出"}

