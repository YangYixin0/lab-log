#!/bin/bash
# 使用国内镜像源安装依赖

# 设置镜像源（阿里云）
INDEX_URL="http://mirrors.cloud.aliyuncs.com/pypi/simple/"

echo "使用镜像源: $INDEX_URL"
echo "正在安装依赖..."

cd "$(dirname "$0")/.."
uv pip install --index-url "$INDEX_URL" -r requirements.txt

echo "依赖安装完成！"
