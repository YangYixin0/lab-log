# Nginx 配置说明

## 配置文件

- `nginx/lab-log.conf` - Lab Log 系统的 Nginx 配置文件

## 安装 Nginx

### Ubuntu/Debian
```bash
sudo apt update
sudo apt install nginx
```

### CentOS/RHEL
```bash
sudo yum install nginx
```

## 配置步骤

### 1. 复制配置文件

```bash
sudo cp nginx/lab-log.conf /etc/nginx/conf.d/lab-log.conf
```

### 2. 测试配置

```bash
sudo nginx -t
```

### 3. 重载 Nginx

```bash
sudo systemctl reload nginx
```

或者

```bash
sudo nginx -s reload
```

## 配置说明

- **监听端口**: 50001
- **前端代理**: `http://127.0.0.1:5173` (Vite 开发服务器)
- **后端代理**: `http://127.0.0.1:8000` (FastAPI)
- **API 路径**: `/api/` 代理到后端
- **其他路径**: 代理到前端

## 访问地址

启动后访问：
- 统一入口: http://localhost:50001
- 前端: http://localhost:50001
- API: http://localhost:50001/api/
- API 文档: http://localhost:50001/api/docs

## 故障排查

### 查看 Nginx 错误日志
```bash
sudo tail -f /var/log/nginx/error.log
```

### 查看 Nginx 访问日志
```bash
sudo tail -f /var/log/nginx/access.log
```

### 检查端口占用
```bash
sudo netstat -tlnp | grep 50001
# 或
sudo ss -tlnp | grep 50001
```

### 重启 Nginx
```bash
sudo systemctl restart nginx
```

## 生产环境建议

1. 使用 HTTPS（配置 SSL 证书）
2. 配置防火墙规则
3. 调整 `client_max_body_size` 根据实际需求
4. 配置日志轮转
5. 启用 gzip 压缩
6. 配置缓存策略

