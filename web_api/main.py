"""FastAPI 应用入口"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from web_api.routers import auth, users, admin

app = FastAPI(
    title="Lab Log API",
    description="实验室日志系统 API",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite 默认端口
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin.router)


@app.get("/")
def root():
    """根路径"""
    return {"message": "Lab Log API", "version": "1.0.0"}


@app.get("/health")
def health():
    """健康检查"""
    return {"status": "ok"}

