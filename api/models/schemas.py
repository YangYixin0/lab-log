"""Pydantic 数据模型"""

from typing import Optional
from pydantic import BaseModel


class UserRegister(BaseModel):
    """用户注册请求"""
    username: str
    password: str  # 必填
    public_key_pem: str  # 必填（注册时自动生成）


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str
    password: str  # 必填
    public_key_pem: Optional[str] = None  # 不再使用公钥登录


class UserResponse(BaseModel):
    """用户信息响应"""
    user_id: str
    username: str
    role: str


class QRCodeResponse(BaseModel):
    """二维码响应"""
    user_id: str
    public_key_fingerprint: str
    qrcode_data: str  # JSON 字符串，用于生成二维码


class TableListResponse(BaseModel):
    """表列表响应"""
    tables: list[str]


class TableDataResponse(BaseModel):
    """表数据响应"""
    table_name: str
    columns: list[dict]
    data: list[dict]
    total: int
    page: int
    limit: int
    total_pages: int


class VectorSearchRequest(BaseModel):
    """向量搜索请求"""
    query: str
    limit: int = 10  # 返回结果数量，默认 10


class VectorSearchResult(BaseModel):
    """向量搜索结果项"""
    chunk_id: str
    chunk_text: str
    related_event_ids: str
    start_time: str
    end_time: str
    distance: float


class VectorSearchResponse(BaseModel):
    """向量搜索响应"""
    query: str
    results: list[VectorSearchResult]
    total: int

