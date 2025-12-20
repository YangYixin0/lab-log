#!/bin/bash
# 启动 Lab Log 系统（后端 + 前端 + Nginx）

cd "$(dirname "$0")"

# 颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 启动 Lab Log 系统...${NC}"
echo ""

# 检查后端依赖
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  虚拟环境不存在，正在创建...${NC}"
    uv venv
    uv pip install -r requirements.txt
    echo ""
fi

# 检查前端依赖是否已安装
if [ ! -d "web_ui/node_modules" ]; then
    echo -e "${YELLOW}⚠️  前端依赖未安装，正在安装...${NC}"
    cd web_ui
    npm install
    cd ..
    echo ""
fi

# 检查 nginx 是否安装
if ! command -v nginx &> /dev/null; then
    echo -e "${RED}❌ Nginx 未安装，请先安装 nginx${NC}"
    echo "  Ubuntu/Debian: sudo apt install nginx"
    echo "  CentOS/RHEL: sudo yum install nginx"
    exit 1
fi

# 启动后端 API（后台运行）
echo -e "${BLUE}📡 启动后端 API (端口 8000)...${NC}"
uv run uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 > /tmp/lab-log-api.log 2>&1 &
API_PID=$!
echo "  后端 PID: $API_PID"
echo "  日志文件: /tmp/lab-log-api.log"
echo ""

# 等待后端启动
sleep 2

# 启动前端（后台运行）
echo -e "${BLUE}🎨 启动前端开发服务器 (端口 5173)...${NC}"
cd web_ui
npm run dev > /tmp/lab-log-frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo "  前端 PID: $FRONTEND_PID"
echo "  日志文件: /tmp/lab-log-frontend.log"
echo ""

# 等待前端启动
sleep 3

# 配置 Nginx
NGINX_CONF_DIR="/etc/nginx/conf.d"
NGINX_CONF_FILE="$NGINX_CONF_DIR/lab-log.conf"
LOCAL_CONF="$(pwd)/nginx/lab-log.conf"

echo -e "${BLUE}⚙️  配置 Nginx...${NC}"

# 检查是否有权限写入 /etc/nginx/conf.d
if [ -w "$NGINX_CONF_DIR" ]; then
    # 有权限，复制配置文件
    sudo cp "$LOCAL_CONF" "$NGINX_CONF_FILE" 2>/dev/null || cp "$LOCAL_CONF" "$NGINX_CONF_FILE"
    echo "  配置文件: $NGINX_CONF_FILE"
else
    # 无权限，提示用户手动配置
    echo -e "${YELLOW}⚠️  需要 root 权限配置 Nginx${NC}"
    echo "  请运行以下命令："
    echo "  sudo cp $LOCAL_CONF $NGINX_CONF_FILE"
    echo "  sudo nginx -t"
    echo "  sudo systemctl reload nginx"
    echo ""
fi

# 测试 Nginx 配置
if sudo nginx -t 2>/dev/null || nginx -t 2>/dev/null; then
    echo "  ✓ Nginx 配置测试通过"
    
    # 重载 Nginx
    if sudo systemctl reload nginx 2>/dev/null || sudo nginx -s reload 2>/dev/null; then
        echo "  ✓ Nginx 已重载"
    else
        echo -e "${YELLOW}⚠️  Nginx 重载失败，请手动运行: sudo systemctl reload nginx${NC}"
    fi
else
    echo -e "${RED}❌ Nginx 配置测试失败${NC}"
    echo "  请检查配置文件: $NGINX_CONF_FILE"
fi

echo ""

# 保存 PID 到文件
echo "$API_PID" > /tmp/lab-log-api.pid
echo "$FRONTEND_PID" > /tmp/lab-log-frontend.pid

echo -e "${GREEN}✅ 服务已启动！${NC}"
echo ""
echo "📍 访问地址："
echo "  - 统一入口: http://localhost:50001"
echo "  - 前端: http://localhost:50001"
echo "  - API: http://localhost:50001/api/"
echo "  - API 文档: http://localhost:50001/api/docs"
echo "  - 健康检查: http://localhost:50001/health"
echo ""
echo "📋 查看日志："
echo "  - 后端: tail -f /tmp/lab-log-api.log"
echo "  - 前端: tail -f /tmp/lab-log-frontend.log"
echo "  - Nginx: sudo tail -f /var/log/nginx/error.log"
echo ""
echo "🛑 停止服务："
echo "  - 运行: ./stop.sh"
echo "  - 或手动: kill $API_PID $FRONTEND_PID"
echo ""

# 等待用户中断（Ctrl+C）
trap "echo ''; echo -e '${YELLOW}正在停止服务...${NC}'; kill $API_PID $FRONTEND_PID 2>/dev/null; rm -f /tmp/lab-log-api.pid /tmp/lab-log-frontend.pid; exit" INT TERM

echo "按 Ctrl+C 停止所有服务"
wait

