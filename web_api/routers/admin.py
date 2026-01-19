"""Admin 专用路由"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from web_api.models.schemas import (
    TableListResponse, 
    TableDataResponse,
    VectorSearchRequest,
    VectorSearchResponse,
    VectorSearchResult
)
from web_api.dependencies import get_db, get_current_user
from storage.seekdb_client import SeekDBClient
from indexing.embedding_service import EmbeddingService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tables", response_model=TableListResponse)
def get_tables(
    current_user: dict = Depends(get_current_user),
    db: SeekDBClient = Depends(get_db)
):
    """获取所有表名（需要管理员权限）"""
    # 检查管理员权限
    if current_user['role'] != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    
    try:
        tables = db.get_table_names()
        # 过滤掉系统表
        allowed_tables = ['users', 'logs_raw', 'logs_embedding', 'tickets', 'field_encryption_keys', 'person_appearances']
        tables = [t for t in tables if t in allowed_tables]
        return TableListResponse(tables=tables)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取表列表失败: {str(e)}"
        )


@router.get("/table/{table_name}", response_model=TableDataResponse)
def get_table_data(
    table_name: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: SeekDBClient = Depends(get_db)
):
    """获取表数据（需要管理员权限）"""
    # 检查管理员权限
    if current_user['role'] != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    
    try:
        result = db.get_table_data(table_name, page, limit)
        return TableDataResponse(
            table_name=table_name,
            **result
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取表数据失败: {str(e)}"
        )


@router.post("/vector-search", response_model=VectorSearchResponse)
def vector_search(
    request: VectorSearchRequest,
    current_user: dict = Depends(get_current_user),
    db: SeekDBClient = Depends(get_db)
):
    """向量搜索（需要管理员权限）"""
    # 检查管理员权限
    if current_user['role'] != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    
    try:
        # 1. 生成查询向量
        embedding_service = EmbeddingService()
        query_vector = embedding_service.embed_text(request.query)
        
        # 2. 执行向量搜索
        search_results = db.vector_search(query_vector, limit=request.limit)
        
        # 3. 转换为响应格式
        results = [
            VectorSearchResult(
                chunk_id=result['chunk_id'],
                chunk_text=result['chunk_text'],
                related_event_ids=result['related_event_ids'],
                start_time=result['start_time'] or '',
                end_time=result['end_time'] or '',
                distance=result['distance'] or 0.0
            )
            for result in search_results
        ]
        
        return VectorSearchResponse(
            query=request.query,
            results=results,
            total=len(results)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"向量搜索失败: {str(e)}"
        )
