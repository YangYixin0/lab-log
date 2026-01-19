"""用户相关路由"""

import json
from fastapi import APIRouter, Depends, HTTPException, status
from web_api.models.schemas import UserResponse, QRCodeResponse
from web_api.dependencies import get_db, get_current_user
from web_api.auth import calculate_public_key_fingerprint
from storage.seekdb_client import SeekDBClient

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse(
        user_id=current_user['user_id'],
        username=current_user['username'],
        role=current_user['role']
    )


@router.get("/me/qrcode", response_model=QRCodeResponse)
def get_qrcode(
    current_user: dict = Depends(get_current_user),
    db: SeekDBClient = Depends(get_db)
):
    """生成用户二维码"""
    # 获取用户完整信息（包括公钥）
    user = db.get_user_by_id(current_user['user_id'])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 计算公钥指纹
    fingerprint = calculate_public_key_fingerprint(user['public_key_pem'])
    
    # 生成二维码数据（JSON 格式）
    qrcode_data = {
        "user_id": user['user_id'],
        "public_key_fingerprint": fingerprint
    }
    
    return QRCodeResponse(
        user_id=user['user_id'],
        public_key_fingerprint=fingerprint,
        qrcode_data=json.dumps(qrcode_data, ensure_ascii=False)
    )

