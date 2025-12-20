#!/bin/bash
# Nginx 快速配置脚本

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}⚙️  配置 Nginx...${NC}"

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}❌ 请使用 sudo 运行此脚本${NC}"
    exit 1
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONF_FILE="$SCRIPT_DIR/lab-log.conf"
NGINX_CONF_DIR="/etc/nginx/conf.d"
NGINX_CONF_FILE="$NGINX_CONF_DIR/lab-log.conf"

# 复制配置文件
echo "  复制配置文件..."
cp "$CONF_FILE" "$NGINX_CONF_FILE"
echo "  ✓ 配置文件已复制到: $NGINX_CONF_FILE"

# 测试配置
echo "  测试 Nginx 配置..."
if nginx -t; then
    echo "  ✓ 配置测试通过"
else
    echo -e "${RED}❌ 配置测试失败${NC}"
    exit 1
fi

# 重载 Nginx
echo "  重载 Nginx..."
if systemctl reload nginx 2>/dev/null || nginx -s reload 2>/dev/null; then
    echo "  ✓ Nginx 已重载"
else
    echo -e "${YELLOW}⚠️  Nginx 重载失败，请手动运行: systemctl reload nginx${NC}"
fi

echo ""
echo -e "${GREEN}✅ Nginx 配置完成！${NC}"
echo ""
echo "📍 访问地址: http://localhost:50001"
