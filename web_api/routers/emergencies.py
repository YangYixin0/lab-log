from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from web_api.dependencies import get_db, get_current_user
from storage.seekdb_client import SeekDBClient

router = APIRouter(prefix="/emergencies", tags=["emergencies"])

class EmergencyResponse(BaseModel):
    emergency_id: str
    description: str
    status: str
    start_time: datetime
    end_time: datetime
    segment_id: str
    created_at: datetime
    resolved_at: Optional[datetime] = None

class EmergencyCountResponse(BaseModel):
    count: int

@router.get("/pending_count", response_model=EmergencyCountResponse)
def get_pending_count(
    current_user: dict = Depends(get_current_user),
    db: SeekDBClient = Depends(get_db)
):
    """获取待处理紧急情况数量"""
    # 仅管理员可查看
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    
    try:
        count = db.get_pending_emergency_count()
        return EmergencyCountResponse(count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list", response_model=List[EmergencyResponse])
def list_emergencies(
    status: Optional[str] = Query(None, description="过滤状态: PENDING 或 RESOLVED"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: SeekDBClient = Depends(get_db)
):
    """获取紧急情况列表"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    
    offset = (page - 1) * limit
    try:
        emergencies = db.get_emergencies(status=status, limit=limit, offset=offset)
        return emergencies
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{emergency_id}/resolve")
def resolve_emergency(
    emergency_id: str,
    current_user: dict = Depends(get_current_user),
    db: SeekDBClient = Depends(get_db)
):
    """解决紧急情况"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    
    try:
        success = db.resolve_emergency(emergency_id)
        if not success:
            raise HTTPException(status_code=404, detail="紧急情况不存在")
        return {"message": "已解决"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
