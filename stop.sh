#!/bin/bash
# 停止 Lab Log 系统的所有服务

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}🛑 正在停止服务...${NC}"

# 从 PID 文件读取并停止进程
if [ -f /tmp/lab-log-api.pid ]; then
    API_PID=$(cat /tmp/lab-log-api.pid)
    if ps -p $API_PID > /dev/null 2>&1; then
        kill $API_PID 2>/dev/null
        echo "  ✓ 后端 API 已停止 (PID: $API_PID)"
    fi
    rm -f /tmp/lab-log-api.pid
fi

if [ -f /tmp/lab-log-frontend.pid ]; then
    FRONTEND_PID=$(cat /tmp/lab-log-frontend.pid)
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        kill $FRONTEND_PID 2>/dev/null
        echo "  ✓ 前端服务已停止 (PID: $FRONTEND_PID)"
    fi
    rm -f /tmp/lab-log-frontend.pid
fi

# 清理可能残留的进程
pkill -f "uvicorn web_api.main:app" 2>/dev/null
pkill -f "vite" 2>/dev/null

# 注意：Nginx 不会自动停止，需要手动停止或保持运行
echo -e "${GREEN}✅ 应用服务已停止${NC}"
echo ""
echo "ℹ️  Nginx 仍在运行（如需停止，运行: sudo systemctl stop nginx）"

