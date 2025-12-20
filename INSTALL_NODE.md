# 安装 Node.js 和 npm

## 方法 1：使用 NodeSource（推荐）

```bash
# 安装 Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 验证安装
node --version
npm --version
```

## 方法 2：使用 nvm（Node Version Manager）

```bash
# 安装 nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# 重新加载 shell 配置
source ~/.bashrc

# 安装 Node.js 20
nvm install 20
nvm use 20

# 验证安装
node --version
npm --version
```

## 方法 3：使用系统包管理器（版本可能较旧）

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install nodejs npm

# 验证安装
node --version
npm --version
```

## 安装前端依赖

安装 Node.js 后，运行：

```bash
cd /root/lab-log/web_ui
npm install
```

## 启动服务

```bash
cd /root/lab-log
./start.sh
```

## 访问地址

- 通过 Nginx: http://<服务器IP>:50001
- 直接访问前端: http://<服务器IP>:5173

