# Web UI 使用说明

## 快速开始

### 1. 安装依赖

#### 后端依赖
```bash
cd /root/lab-log
pip install -r requirements.txt
```

#### 前端依赖
```bash
cd /root/lab-log/web_ui
npm install
```

### 2. 初始化数据库

确保数据库 schema 已更新（包含 role 和 password_hash 字段）：

```bash
cd /root/lab-log
python3 scripts/init_database.py
```

这将创建 admin 用户：
- 用户名: `admin`
- 密码: `admin`
- 角色: `admin`

### 3. 启动后端 API

```bash
cd /root/lab-log
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

API 文档：http://localhost:8000/docs

### 4. 启动前端

```bash
cd /root/lab-log/web_ui
npm run dev
```

前端地址：http://localhost:5173

## 功能说明

### 用户注册
- 支持用户名 + 密码注册
- 支持用户名 + 公钥注册
- 支持自动生成密钥对（使用 WebCrypto API）
- 默认角色为 `user`

### 用户登录
- 支持用户名 + 密码登录
- 支持用户名 + 公钥登录（简化版，仅比较公钥是否匹配）

### 二维码展示
- 显示用户 ID 和公钥指纹（SHA256）
- 二维码内容为 JSON 格式：`{user_id, public_key_fingerprint}`
- 用于向视频采集端证明身份

### Admin 功能
- 查看所有数据库表（users, logs_raw, logs_embedding, tickets, field_encryption_keys）
- 实时查看表数据（每 10 秒自动刷新）
- 支持分页浏览
- 加密字段直接显示（不解密）

## 安全说明

- Session Cookie 使用 HttpOnly，防止 XSS 攻击
- 密码使用 bcrypt 哈希存储
- Admin 路由需要权限检查
- CORS 配置仅允许前端域名

## 注意事项

1. **数据库迁移**：如果已有数据库，需要手动更新 users 表：
   ```sql
   ALTER TABLE users ADD COLUMN role ENUM('admin', 'user') DEFAULT 'user';
   ALTER TABLE users ADD COLUMN password_hash VARCHAR(255);
   ALTER TABLE users ADD INDEX idx_role (role);
   UPDATE users SET role = 'admin' WHERE user_id = 'admin';
   ```

2. **Session 存储**：当前使用内存存储 session，生产环境应使用 Redis

3. **公钥验证**：当前公钥登录仅比较公钥是否匹配，生产环境应使用签名验证

