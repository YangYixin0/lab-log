#!/bin/bash
# SeekDB 部署脚本

set -e

echo "开始部署 SeekDB..."

# 检查是否为 root 用户或有 sudo 权限
if [ "$EUID" -ne 0 ] && ! sudo -n true 2>/dev/null; then
    echo "错误: 需要 root 权限或 sudo 权限来安装软件包"
    exit 1
fi

# 添加 seekdb 镜像源
echo "添加 SeekDB 镜像源..."
if command -v yum-config-manager &> /dev/null; then
    sudo yum-config-manager --add-repo https://mirrors.aliyun.com/oceanbase/OceanBase.repo
else
    echo "警告: 未找到 yum-config-manager，尝试手动添加源..."
    sudo tee /etc/yum.repos.d/oceanbase.repo > /dev/null <<EOF
[oceanbase]
name=OceanBase Repository
baseurl=https://mirrors.aliyun.com/oceanbase/
enabled=1
gpgcheck=0
EOF
fi

# 安装 seekdb 和 obclient
echo "安装 seekdb 和 obclient..."
sudo yum install -y seekdb obclient

# 启动 seekdb 服务
echo "启动 seekdb 服务..."
sudo systemctl start seekdb

# 等待服务启动
sleep 3

# 检查服务状态
echo "检查 seekdb 服务状态..."
if sudo systemctl is-active --quiet seekdb; then
    echo "✓ SeekDB 服务已成功启动"
    sudo systemctl status seekdb --no-pager -l
else
    echo "✗ SeekDB 服务启动失败"
    exit 1
fi

# 验证连接
echo "验证 SeekDB 连接..."
if mysql -h127.0.0.1 -uroot -P2881 -A oceanbase -e "SELECT 1;" &>/dev/null; then
    echo "✓ SeekDB 连接成功"
else
    echo "✗ SeekDB 连接失败，请检查服务状态"
    exit 1
fi

echo "SeekDB 部署完成！"
echo "连接命令: mysql -h127.0.0.1 -uroot -P2881 -A oceanbase"

