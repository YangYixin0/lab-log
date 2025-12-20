# 使用 uv 管理 Python 环境和依赖

本项目已配置使用 `uv` 来管理 Python 环境和依赖包。

## 快速开始

### 1. 创建虚拟环境

```bash
cd /root/lab-log
uv venv
```

这会创建 `.venv` 目录作为虚拟环境。

### 2. 激活虚拟环境

```bash
source .venv/bin/activate
```

或者使用 uv 直接运行命令（无需激活）：

```bash
uv run python scripts/init_database.py
```

### 3. 安装依赖

```bash
# 使用 requirements.txt
uv pip install -r requirements.txt

# 或使用 pyproject.toml（如果配置了）
uv pip install -e .
```

### 4. 使用 uv 运行命令

```bash
# 运行脚本
uv run python scripts/init_database.py

# 运行 API 服务器
uv run uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 运行其他 Python 脚本
uv run python scripts/process_video.py ...
```

## 镜像源配置

已配置使用清华镜像源加速下载，配置文件位于 `.uv/config.toml`：

```toml
index-url = "https://pypi.tuna.tsinghua.edu.cn/simple"
```

如果需要使用其他镜像源，可以修改该文件或使用环境变量：

```bash
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

## 常用命令

```bash
# 查看已安装的包
uv pip list

# 安装新包
uv pip install package_name

# 更新包
uv pip install --upgrade package_name

# 卸载包
uv pip uninstall package_name

# 同步依赖（根据 requirements.txt）
uv pip sync requirements.txt
```

## 优势

- **速度快**：uv 使用 Rust 编写，比 pip 快 10-100 倍
- **可靠**：更好的依赖解析和锁定
- **简单**：统一的工具管理虚拟环境和包

## 注意事项

- 虚拟环境位于 `.venv/` 目录
- `.venv/` 已在 `.gitignore` 中，不会提交到版本控制
- 使用 `uv run` 时无需手动激活虚拟环境

