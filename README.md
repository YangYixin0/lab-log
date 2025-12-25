# 视频日志系统 MVP 使用说明

## 项目背景

本项目是一个**实验室视觉日志系统**的 MVP（最小可行产品）实现。系统的核心目标是通过相机和视觉大模型，将实验室内的人物动作（使用设备和药品等）和设备运转状态自动记录为结构化文本日志，为更高级的智能体应用和 AI 实验室管家奠定基础。

### 核心特性

- **动态上下文视频理解**：使用动态上下文驱动的视频理解，基于当天事件缓存、人物外貌表缓存和二维码识别结果构建提示词，模型输出续写事件和外貌更新
- **视频理解**：使用 Qwen3-VL Flash 视觉大模型分析实验室视频，自动识别人物动作、设备操作等信息
- **人物外貌管理**：自动维护人物外貌表缓存，支持追加、更新、合并操作，使用并查集管理编号合并关系
- **二维码识别**：Android 采集端实时识别用户二维码，自动关联用户身份与视频片段
- **结构化日志**：将视频内容转换为带时间戳的结构化事件日志（事件不加密，直接写入数据库）
- **字段级加密**：支持对敏感字段（如人物外观特征）进行加密，使用混合加密方案（AES-GCM + RSA-OAEP）（日终处理时对人物外貌表加密）
- **向量检索**：支持日志的向量嵌入和语义搜索，便于后续的智能查询和分析
- **Web 前端**：提供用户友好的 Web 界面，支持用户注册、登录、查看数据和管理功能
- **权限管理**：支持用户角色（admin/user），admin 用户可以查看数据库和进行向量搜索

### 系统架构

系统采用模块化设计，主要包含以下模块：

- **视频接入**：支持 MP4 视频文件处理（未来可扩展为流式处理）
- **视频分段**：使用关键帧对齐将长视频分割为处理段（约 60 秒），支持迭代式分段确保连续性
- **动态上下文**：维护当天事件缓存（最新 n 条）和人物外貌表缓存（全量），用于构建模型提示词
- **视频理解**：调用 Qwen3-VL Flash API 进行视频内容分析，使用动态上下文生成续写事件和外貌更新
- **人物外貌管理**：使用并查集管理人物编号合并关系，支持追加、更新、合并操作
- **日志写入**：将识别的事件直接写入数据库（不加密），人物外貌表缓存在内存/文件，日终再加密入库
- **向量嵌入**：对日志进行分块和向量化，支持语义搜索
- **存储**：使用 SeekDB 作为数据库，支持关系型、向量和全文搜索
- **Web 前端**：React + Vite 构建的用户界面，提供数据查看和管理功能
- **后端 API**：FastAPI 构建的 RESTful API，支持用户认证和数据访问
- **流媒体服务器**：WebSocket 服务器，接收 Android 端推送的 MP4 分段（经 H.264 编码），串行处理并写入日志 / 索引

## 工作流程

### 整体流程（逻辑视角）

#### 动态上下文模式（默认）

```
视频文件 (MP4) + 二维码识别结果
    ↓
[视频分段] 关键帧对齐，分为多个约 60 秒的片段（迭代式分段确保连续性）
    ↓
[动态上下文构建]
    ├─ 查询当天最新 n 条事件（从 JSONL 文件 logs_debug/event_logs.jsonl）
    ├─ 加载人物外貌表缓存（从内存/文件 logs_debug/appearances_today.json）
    └─ 获取二维码识别结果（从分段元数据）
    ↓
[视频理解] 调用 Qwen3-VL Flash，输入动态上下文，输出：
    ├─ events_to_append: 续写的事件列表
    └─ appearance_updates: 外貌更新（add/update/merge）
    ↓
[事件写入] 立即写入 SeekDB 数据库（不加密）+ 调试 JSONL 文件
    ↓
[外貌更新] 更新人物外貌表缓存（内存）
    ↓
[周期性保存] 每处理 N 个分段，dump 外貌缓存到文件
    ↓
[日终处理] 并查集压缩 → 加密 user_id → 写入数据库 → 更新事件 person_ids → 触发索引
    ↓
完成
```

#### 传统模式（兼容）

```
视频文件 (MP4)
    ↓
[视频分段] 关键帧对齐，分为多个约 60 秒的片段（迭代式分段确保连续性）
    ↓
[视频理解] 对每个片段调用 Qwen3-VL Flash，提取事件
    ↓
[日志生成] 将识别的事件转换为结构化 EventLog
    ↓
[字段加密] 对配置的敏感字段进行混合加密（如人物外观）
    ↓
[数据写入] 写入 SeekDB 数据库 + 调试 JSONL 文件
    ↓
[可选] [日志分块] 使用配置的分块策略聚合事件（默认：每个事件一个块）
    ↓
[可选] [向量嵌入] 使用 Qwen text-embedding-v4 生成 1024 维向量
    ↓
[可选] [向量索引] 写入 logs_embedding 表，支持向量搜索
    ↓
完成
```

### 两种处理路径

1) **实时处理（Android 采集端 → WebSocket 服务器）**
   - Android 端用 MediaCodec 编码 H.264，并在关键帧前附带完整 SPS/PPS（关键经验：给 IDR 帧前置 SPS/PPS，保证每段 MP4 可独立解码），使用 MediaMuxer 生成小 MP4 分段，通过 WebSocket 发送到服务器。
   - **二维码识别**：采集过程中使用 ML Kit 实时识别用户二维码，按分段聚合识别结果（同一用户保留最高置信度），随 MP4 分段元数据一起上报。识别成功时播放提示音并在预览层显示提示。
   - 服务器 `streaming_server` 接收 Base64 MP4 文本消息（包含二维码识别结果），保存到 `recordings/<timestamp>/` 目录：
     - MP4 分段保存为 `{segment_id}.mp4`
     - 二维码识别结果保存为 `{segment_id}_qr.json`
   - 如果启用实时处理，立即进行视频理解并写入数据库；否则仅保存文件，后续可使用 `scripts/process_recording_session.py` 处理。
   - **动态上下文模式**（默认启用）：
     - 每个会话维护独立的人物外貌缓存（AppearanceCache）
     - 从 JSONL 文件（`logs_debug/event_logs.jsonl`）读取当天最新 n 条事件作为上下文
     - 启动时自动加载已存在的外貌缓存文件（`logs_debug/appearances_today.json`）
     - 模型输出续写事件和外貌更新，事件立即入库（不加密），外貌更新写入缓存
     - 每处理 N 个分段，自动保存外貌缓存到 `logs_debug/appearances_today.json`
   - 处理管线：动态上下文构建 → Qwen3-VL Flash → 解析双输出 → 事件写入 logs_raw（不加密）→ 外貌更新缓存 → 生成缩略图 → 单行 Realtime 日志输出。

2) **离线处理（已有 MP4 文件）**
   - 使用 `scripts/process_video.py /path/to/video.mp4` 直接跑 VideoLogPipeline。
   - 生成事件日志（logs_raw / event_logs.jsonl），每个分段理解后立即写入数据库。
   - 索引需要手动触发：使用 `scripts/index_events.py` 对未索引的事件进行分块和嵌入。

3) **处理已保存的采集会话**
   - 使用 `scripts/process_recording_session.py recordings/<session_dir>` 处理一次采集会话的所有分段。
   - 自动读取会话目录下的 MP4 分段和对应的二维码识别结果（`*_qr.json` 文件）。
   - 每个分段理解后立即写入数据库，二维码结果会传递给视频理解部分（当前暂不使用）。
   - 适用于处理实时采集后保存的会话数据，或重新处理历史会话。

### 数据流

1. **视频分段**：
   - 使用 ffprobe 检测所有关键帧（I 帧）位置
   - 以关键帧为边界进行分段，每个分段约 60 秒
   - 采用迭代式分段：每提取一个分段后，检查实际结束时间，从那里开始下一个分段
   - 确保分段连续且无重叠，每个分段不超过 5 分钟
2. **视频理解**（动态上下文模式）：
   - 构建动态提示词：包含视频片段、二维码识别结果、当天最新 n 条事件（从 JSONL 文件读取）、人物外貌表全量（从缓存文件加载）
   - 调用 Qwen3-VL API 分析视频内容（可通过环境变量选择 Flash 或 Plus 模型）
   - 模型输出两部分：
     - `events_to_append`：续写的事件列表（event_id, start_time, end_time, event_type, person_ids, equipment, description）
     - `appearance_updates`：外貌更新操作（add/update/merge）
   - 应用外貌更新到缓存（使用并查集管理合并关系）
   - 生成结构化的事件列表（EventLog），事件不加密直接写入数据库和 JSONL 文件
3. **数据存储**（动态上下文模式）：
   - 事件立即写入 SeekDB 的 `logs_raw` 表（不加密，structured 字段包含 person_ids 列表）
   - 同时写入 `logs_debug/event_logs.jsonl` 用于调试
   - 人物外貌表缓存在内存中，每处理 N 个分段自动保存到 `logs_debug/appearances_today.json`
   - 每个分段理解后立即写入数据库，不等待所有分段完成
4. **日终处理**（可选）：
   - 使用 `scripts/end_of_day.py` 执行日终处理
   - 加载外貌缓存，执行并查集去重压缩
   - 加密 user_id 并写入数据库
   - 更新数据库中事件的 person_ids（将被合并编号替换为主编号）
   - 触发索引（分块和嵌入）
5. **索引构建**（手动触发）：
   - 使用 `scripts/index_events.py` 手动触发索引
   - 对未索引的事件（`is_indexed = FALSE`）进行分块和嵌入
   - 使用配置的分块策略聚合事件日志（默认：每个事件一个块）
   - 生成文本向量嵌入（Qwen text-embedding-v4，1024 维）
   - 写入 `logs_embedding` 表，支持后续的向量搜索
   - 索引完成后，将相关事件的 `is_indexed` 字段更新为 `TRUE`

## 快速开始

### 1. 部署 SeekDB

本项目使用 Docker 部署 SeekDB。

#### 1.1 首次部署

使用以下命令启动 SeekDB 容器：

```bash
docker run -d \
  --name seekdb \
  -p 2881:2881 \
  quay.io/oceanbase/seekdb:latest
```

该命令将：
- 从 quay.io 拉取 SeekDB 镜像（如果本地不存在）
- 创建并启动名为 `seekdb` 的容器
- 将容器的 2881 端口映射到主机的 2881 端口

**注意**：首次启动时，SeekDB 需要一些时间进行初始化（通常需要 10-30 秒），请耐心等待。

#### 1.2 启动已存在的容器

如果容器已经创建但已停止，使用以下命令启动：

```bash
# 查看容器状态
docker ps -a | grep seekdb

# 启动容器
docker start seekdb

# 等待初始化完成（约 10-30 秒）
sleep 15
```

#### 1.3 验证部署

```bash
# 检查容器状态（应该显示 "Up"）
docker ps | grep seekdb

# 查看容器日志（确认初始化完成）
docker logs seekdb | tail -20

# 测试连接（需要安装 MySQL 客户端）
mysql -h127.0.0.1 -uroot -P2881
```

如果连接成功，说明 SeekDB 已准备就绪。

#### 1.4 停止和重启

```bash
# 停止容器
docker stop seekdb

# 启动容器
docker start seekdb

# 重启容器
docker restart seekdb

# 删除容器（数据会丢失，谨慎操作）
docker rm -f seekdb
```

#### 1.5 常见问题

**问题 1：容器启动后无法连接**

- 等待更长时间（SeekDB 初始化需要时间）
- 检查容器日志：`docker logs seekdb`
- 确认端口 2881 未被占用：`netstat -tlnp | grep 2881`

**问题 2：容器已存在但无法启动**

```bash
# 查看容器状态
docker ps -a | grep seekdb

# 如果容器状态为 "Exited"，尝试启动
docker start seekdb

# 如果启动失败，查看日志
docker logs seekdb
```

**问题 3：需要重新初始化数据库**

如果数据库出现问题，可以删除容器并重新创建（**注意：这会丢失所有数据**）：

```bash
# 停止并删除容器
docker stop seekdb
docker rm seekdb

# 重新创建容器
docker run -d \
  --name seekdb \
  -p 2881:2881 \
  quay.io/oceanbase/seekdb:latest

# 等待初始化完成后，重新运行初始化脚本
sleep 20
python scripts/init_database.py
```

### 2. 配置环境变量

创建 `.env` 文件：

```bash
# DashScope API Key（用于 Qwen3-VL 和 embedding）
DASHSCOPE_API_KEY=your_api_key_here

# 加密配置（可选）
ENCRYPTION_ENABLED=true
ENCRYPTION_TEST_USER_ID=admin

# 实时处理配置（可选）
REALTIME_PROCESSING_ENABLED=true  # 是否启用实时处理（默认true）
REALTIME_TARGET_SEGMENT_DURATION=60.0  # 目标分段时长（秒，默认60）
REALTIME_QUEUE_ALERT_THRESHOLD=10  # 队列告警阈值（默认10）
REALTIME_CLEANUP_H264=true  # 是否清理H264临时文件（默认true）
WEBSOCKET_MAX_SIZE_MB=50.0  # WebSocket消息最大大小（MB，默认50.0，用于接收MP4分段）
WEBSOCKET_VERBOSE=false  # 是否启用WebSocket调试日志（默认false）

# 动态上下文配置（可选）
DYNAMIC_CONTEXT_ENABLED=true  # 是否启用动态上下文（默认true）
MAX_RECENT_EVENTS=20  # 最大最近事件数（默认20）
APPEARANCE_DUMP_INTERVAL=1  # 外貌缓存保存间隔（每处理N个分段保存一次，默认1）

# start 命令默认参数（可选，用于流媒体服务器终端命令）
DEFAULT_INCLUDE_ASPECT_RATIO=false   # 是否在 start 命令中默认包含 aspectRatio（默认false，即使用客户端UI选择的宽高比）
DEFAULT_ASPECT_RATIO_WIDTH=4        # 默认宽高比宽度（默认4）
DEFAULT_ASPECT_RATIO_HEIGHT=3       # 默认宽高比高度（默认3）
DEFAULT_BITRATE_MB=1.0               # 默认码率（MB，默认1.0）
DEFAULT_FPS=4                       # 默认帧率（默认4）

# 视频理解模型配置（可选）
QWEN_MODEL=qwen3-vl-flash  # 模型名称：qwen3-vl-flash 或 qwen3-vl-plus（默认 qwen3-vl-flash）
VIDEO_FPS=2.0  # 视频抽帧率，表示每隔 1/fps 秒抽取一帧（默认 2.0）
ENABLE_THINKING=true  # 是否启用思考（默认true）
THINKING_BUDGET=8192  # 思考预算（tokens，默认8192）
VL_HIGH_RESOLUTION_IMAGES=true  # 是否启用高分辨率图像处理（默认 true）
VL_TEMPERATURE=0.1  # 模型温度参数，控制输出随机性（默认 0.1）
VL_TOP_P=0.7  # Top-p 采样参数，控制输出多样性（默认 0.7）

# 注意：索引已不再由视频处理触发，统一由独立脚本处理（如 scripts/index_events.py）

# 数据库配置（可选，使用默认值）
SEEKDB_HOST=127.0.0.1
SEEKDB_PORT=2881
SEEKDB_DATABASE=lab_log
SEEKDB_USER=root
SEEKDB_PASSWORD=  # 如果无密码，请留空（SeekDB 默认 root 用户密码为空）
```

**注意**：数据库配置会在初始化数据库时使用。如果使用默认值，可以省略数据库配置项。

### 3. 初始化数据库

```bash
# 如果使用虚拟环境，先激活（或直接使用 .venv/bin/python）
source .venv/bin/activate
python scripts/init_database.py

# 或者不激活，直接使用虚拟环境的 Python
.venv/bin/python scripts/init_database.py
```

这将：
- 创建数据库和表结构
- 创建测试用户 `admin`
- 生成 RSA 密钥对（私钥保存在 `scripts/test_keys/admin_private_key.pem`）

**注意**：初始化脚本会自动读取 `.env` 文件中的数据库配置。如果未配置，将使用默认值（127.0.0.1:2881, root, lab_log, 密码为空）。

### 4. 安装依赖

#### 4.1 安装 Python 依赖

本项目使用 **uv** 作为包管理工具，并推荐使用虚拟环境。

**方法 1：使用安装脚本（推荐，自动使用国内镜像源）**

```bash
./scripts/install_deps.sh
```

该脚本会自动：
- 创建虚拟环境（如果不存在）
- 使用国内镜像源加速安装
- 安装所有依赖包

**方法 2：手动使用 uv 安装**

```bash
# 创建虚拟环境
uv venv

# 安装依赖（使用国内镜像源加速）
uv pip install --index-url http://mirrors.cloud.aliyuncs.com/pypi/simple/ -r requirements.txt
```

#### 4.2 安装 Node.js 和前端依赖

前端使用 React + Vite，需要安装 Node.js 和 npm。

**安装 Node.js**（如果未安装）：

```bash
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# 验证安装
node --version
npm --version
```

**安装前端依赖**：

```bash
cd web_ui
npm install
cd ..
```

或者使用启动脚本自动安装（见下一节）。

### 5. 启动 Web 服务

系统提供了统一的启动脚本，会自动启动后端 API、前端开发服务器和配置 Nginx。

```bash
# 启动所有服务（后端 + 前端 + Nginx）
./start.sh
```

该脚本会：
- 检查并创建虚拟环境（如需要）
- 检查并安装前端依赖（如需要）
- 启动后端 API（端口 8000）
- 启动前端开发服务器（端口 5173）
- 配置 Nginx 反向代理（端口 50001）

**访问地址**：
- 统一入口：http://localhost:50001
- API 文档：http://localhost:50001/api/docs
- 健康检查：http://localhost:50001/health

**停止服务**：

```bash
./stop.sh
```

**查看日志**：

```bash
# 后端日志
tail -f /tmp/lab-log-api.log

# 前端日志
tail -f /tmp/lab-log-frontend.log

# Nginx 日志
sudo tail -f /var/log/nginx/error.log
```

### 6. 启动流媒体服务器（用于实时采集）

流媒体服务器用于接收 Android App 推送的 H264 视频流，并进行实时处理和日志记录。

```bash
# 如果使用虚拟环境，先激活（或直接使用 .venv/bin/python）
source .venv/bin/activate
python streaming_server/server.py

# 或者不激活，直接使用虚拟环境的 Python
.venv/bin/python streaming_server/server.py

# 指定主机和端口（可选）
python streaming_server/server.py --host 0.0.0.0 --port 50001
```

**启动成功后会看到**：
```
WebSocket server started at ws://0.0.0.0:50001
You can now connect your Android Camera App.
[Info]: Realtime processing enabled (target segment duration: 60.0s)

Enter command ('start [w]:[h] [bitrate_mb] [fps]' or 'stop'): 
  Example: 'start 4:3 4 10' for 4:3 aspect ratio, 4 MB bitrate, 10 fps
  Defaults (from env): aspect=4:3, bitrate=1.0MB, fps=10, include_aspect=False
> 
```

**功能说明**：
- 默认监听 `0.0.0.0:50001`（可通过参数修改）
- 支持实时处理：自动检测关键帧并分段处理视频
- 支持终端命令控制：输入 `start` 开始录制，`stop` 停止录制
- **start 命令默认参数**：可通过环境变量配置（见上方环境变量配置部分）
  - 如果只输入 `start`（无参数），会使用环境变量中的默认值
  - 如果输入 `start 16:9 4 15`，会使用命令行参数（优先级高于环境变量）
  - 如果 `DEFAULT_INCLUDE_ASPECT_RATIO=false`（默认），`start` 命令不会发送 `aspectRatio`，客户端会使用 UI 选择的宽高比
  - 如果 `DEFAULT_INCLUDE_ASPECT_RATIO=true`，`start` 命令会发送环境变量中配置的宽高比
- 详细使用说明请参考 `android-camera/README.md`

**停止服务器**：
- 按 `Ctrl+C` 停止服务器

**测试服务器（仅用于验证二维码识别功能）**：

如果只需要测试二维码识别功能，可以使用轻量级的测试服务器：

```bash
# 启动测试服务器（端口 50003）
python streaming_server/test_qr_server.py
```

测试服务器功能：
- 接收 MP4 分段并保存到 `qr_test_segments/` 目录
- 打印收到的二维码识别结果（`qr_results`）
- 支持终端命令控制（`start` / `stop`）
- **不进行视频处理**，仅用于验证二维码识别和上报功能

### 7. 处理视频（离线处理）

#### 7.1 处理未分段的完整视频

处理已录制的完整 MP4 视频文件（会自动分段）：

```bash
# 如果使用虚拟环境，先激活（或直接使用 .venv/bin/python）
source .venv/bin/activate
python scripts/process_video.py /path/to/video.mp4

# 或者不激活，直接使用虚拟环境的 Python
.venv/bin/python scripts/process_video.py /path/to/video.mp4
```

**注意**：索引已从视频处理流程中剥离，改为手动触发。请使用 `scripts/index_events.py` 对未索引的事件进行分块和嵌入。

#### 7.2 处理已保存的采集会话

处理实时采集后保存的会话目录（包含 MP4 分段和二维码识别结果）：

```bash
# 处理一次采集会话的所有分段
python scripts/process_recording_session.py recordings/<session_dir>

# 指定分段目标时长（用于解析时间戳失败时的回退）
python scripts/process_recording_session.py recordings/<session_dir> --target-duration 60.0
```

**功能说明**：
- 自动读取会话目录下的所有 MP4 分段文件
- 自动读取对应的二维码识别结果（`{segment_id}_qr.json` 文件）
- 按顺序串行处理每个分段，每个分段理解后立即写入数据库
- 二维码识别结果会传递给视频理解部分（当前暂不使用，但已保存）

**会话目录结构**：
```
recordings/
└── 20251224_163520/
    ├── 20251224_163520_00.mp4
    ├── 20251224_163520_00_qr.json
    ├── 20251224_163521_00.mp4
    ├── 20251224_163521_00_qr.json
    └── ...
```

**连接视频片段（可选）**：

如果需要将会话中的所有视频片段连接成一个完整的视频文件，可以使用 `scripts/concat_videos.py`：

```bash
# 连接会话中的所有视频片段（输出到 <session_dir>/concatenated.mp4）
python scripts/concat_videos.py recordings/<session_dir>

# 指定输出文件路径
python scripts/concat_videos.py recordings/<session_dir> -o output.mp4
```

**功能说明**：
- 自动扫描目录中的所有 `.mp4` 文件并按文件名排序（时间戳顺序）
- 检测每个视频的帧率，找到最高帧率并向上取整作为统一帧率
- 使用 ffmpeg 重新编码并连接所有视频片段
- 输出为 H.264 编码的 MP4 文件，帧率统一，分辨率保持一致

#### 7.3 手动触发索引

对未索引的事件进行分块和嵌入：

```bash
# 处理未索引的事件（默认每次最多处理 1000 个事件，批量大小 100）
python scripts/index_events.py

# 指定处理数量
python scripts/index_events.py --limit 2000 --batch-size 200
```

**功能说明**：
- 自动查询 `is_indexed = FALSE` 的事件
- 分批处理，避免内存溢出
- 索引完成后自动更新 `is_indexed` 字段为 `TRUE`
- 支持多次运行，会自动跳过已索引的事件

### 8. Web 前端功能

系统提供了完整的 Web 前端界面，支持以下功能：

#### 8.1 用户功能

- **用户注册**：
  - 填写用户名和密码（必填）
  - 系统自动生成 RSA 密钥对（无需手动操作）
  - 公钥自动上传到服务器
  - 私钥显示在页面上，提供下载和复制功能
  - **重要**：私钥仅显示一次，请务必妥善保管

- **用户登录**：
  - 使用用户名和密码登录
  - 支持 Session Cookie 管理，自动保持登录状态

- **用户中心**：
  - 查看用户信息（用户 ID、用户名、角色）
  - 查看和下载二维码（包含用户 ID 和公钥指纹）
  - 二维码用于向视频采集端证明身份

#### 8.2 Admin 功能（仅管理员可见）

- **查看数据库**：
  - 查看所有数据库表（users、logs_raw、logs_embedding、field_encryption_keys、tickets）
  - 支持分页浏览表数据
  - 自动刷新（每 10 秒）
  - 智能列宽：vector 类型较窄，text/json 类型较宽，ID 类型完整显示

- **向量搜索**：
  - 输入查询文本进行语义搜索
  - 使用 Qwen text-embedding-v4 生成查询向量
  - 使用余弦距离计算相似度
  - 显示搜索结果（分块文本、时间范围、相似度距离等）
  - 支持设置返回结果数量（1-50）

#### 8.3 导航栏

- 所有用户：用户中心
- Admin 用户：用户中心、查看数据库、向量搜索
- 显示当前用户名和角色标签
- 登出功能

### 9. 工具脚本

项目提供了多个工具脚本用于测试和调试：

```bash
# 处理未分段的完整视频
python scripts/process_video.py <视频文件路径>

# 处理已保存的采集会话（包含二维码结果）
python scripts/process_recording_session.py recordings/<session_dir>

# 手动触发索引（对未索引的事件进行分块和嵌入）
python scripts/index_events.py [--limit 1000] [--batch-size 100]

# 日终处理（外貌缓存压缩、加密入库、更新事件 person_ids）
python scripts/end_of_day.py [--date YYYY-MM-DD] [--dry-run]

# 测试分段功能（不调用大模型）
python scripts/test_segmentation.py <视频文件路径>

# 分析视频关键帧位置和间隔
python scripts/analyze_keyframes.py <视频文件1> [视频文件2] ...

# 从视频中提取片段（自动对齐到关键帧）
python scripts/extract_segment_aligned.py <视频文件> <起始时间> <结束时间> <输出文件>

# 连接录制会话中的视频片段（重新编码并统一帧率）
python scripts/concat_videos.py recordings/<session_dir> [-o output.mp4]

# 测试向量搜索功能
python scripts/test_vector_search.py

# 清空测试数据（包括数据库表、事件日志文件、人物外貌缓存）
python scripts/clear_test_data.py
```

## 功能说明

### 用户认证与权限

- **用户注册**：支持用户名和密码注册，自动生成 RSA 密钥对
- **密码加密**：使用 bcrypt 进行密码哈希存储
- **Session 管理**：使用 Session Cookie 进行会话管理
- **角色权限**：
  - `user`：普通用户，可以查看自己的信息和二维码
  - `admin`：管理员，可以查看所有数据库表和进行向量搜索

### 数据安全

- **字段加密**：敏感字段（如 `person.clothing_color`、`person.hair_color`）在写入数据库前会被加密
- **加密提示**：视频处理提示词中明确说明，敏感信息不能写入未加密字段（如 `raw_text`、`remark` 等）
- **密钥管理**：用户私钥仅在注册时显示一次，必须妥善保管

### 视频分段
- **关键帧对齐**：优先使用关键帧（I 帧）作为分段边界
- **迭代式分段**：每提取一个分段后，检查实际结束时间，从那里开始下一个分段，确保连续且无重叠
- **目标段长**：约 60 秒，但会根据关键帧位置自动调整
- **最大段长限制**：每个分段不超过 5 分钟，确保发送给大模型的视频不会过长
- **回退机制**：如果关键帧太少，自动回退到时间分段

### 动态上下文视频理解
- **动态提示词构建**：基于当天事件缓存（从 JSONL 文件读取最新 n 条）、人物外貌表缓存（从文件加载全量）和二维码识别结果构建提示词
- **模型选择**：支持通过环境变量选择使用 Qwen3-VL Flash 或 Plus 模型
- **模型输出**：模型输出两部分结构化数据
  - `events_to_append`：续写的事件列表（event_id, start_time, end_time, event_type, person_ids, equipment, description）
  - `appearance_updates`：外貌更新操作（add/update/merge）
- **事件类型**：支持三种事件类型
  - `person`：人物事件，包含人物动作和设备操作
  - `equipment-only`：设备事件，仅设备状态变化，无人物参与（person_ids 为空数组）
  - `none`：空事件，画面中既无人物活动也无设备数值变化（person_ids 为空数组，equipment 为空字符串）
- **编号分配规则**：模型分配人物编号（p1, p2...）和事件编号（evt_00001...），新增编号必须大于现存最大编号
- **人物外貌匹配**：
  - 优先重用已有外貌记录（匹配稀有特征）
  - 常见特征一致是匹配的必要条件但不充分
  - 稀有特征一致是合并的强信号
  - 合并方向：小编号合并到大编号（merge_from < target_person_id）
- **外貌表管理**：使用并查集管理人物编号合并关系，支持路径压缩
- **二维码用户关联**：根据二维码识别结果的时间戳，将用户ID关联到对应的人物外貌记录
- **事件上下文来源**：从 `logs_debug/event_logs.jsonl` 文件读取，无需数据库连接，支持离线工作

### 视频理解（传统模式）
- 使用 Qwen3-VL Flash 进行视频理解
- 自动提取人物动作、设备操作等信息
- 从视频画面提取时间戳

### 日志加密
- **事件日志**：动态上下文模式下，事件不加密直接写入数据库
- **人物外貌表**：缓存在内存/文件中（明文），日终处理时加密 user_id 并写入数据库
- **传统模式**：字段级加密（混合加密：AES-GCM + RSA-OAEP）
  - 默认加密字段：`person.clothing_color`, `person.hair_color`
  - 可通过 `config/encryption_config.py` 配置

### 日志分块与嵌入
- **默认行为**：视频处理不进行索引（分块和嵌入），每个分段理解后立即写入数据库
- **索引触发方式**：
  - 手动触发：使用 `scripts/index_events.py` 对未索引的事件进行分块和嵌入
  - 生产环境：在特定时间（如凌晨）通过定时任务调用 `scripts/index_events.py` 批量执行索引
- **索引状态跟踪**：
  - `logs_raw` 表新增 `is_indexed` 字段，标记事件是否已索引
  - 新插入的事件默认 `is_indexed = FALSE`
  - 索引完成后，相关事件的 `is_indexed` 字段更新为 `TRUE`
- **分块策略**：模块化设计，支持多种分块策略
  - 默认策略：每个事件一个块
  - 时间窗口策略：按时间窗口（可配置，默认 7.5 分钟）聚合事件
  - 无人事件间隔策略：以无人事件为间隔进行分块
  - LLM 智能分块策略：预留接口，支持未来使用 LLM 进行语义分块
- **向量嵌入**：使用 Qwen text-embedding-v4 生成 1024 维向量
- **向量搜索**：支持语义搜索，使用余弦距离进行相似度计算

## 目录结构

```
lab-log/
├── streaming_server/    # WebSocket 流媒体服务器
│   ├── server.py            # WebSocket 服务器（接收MP4分段，实时处理）
│   ├── test_qr_server.py    # 测试服务器（仅接收和保存MP4分段，打印二维码识别结果）
│   ├── h264_parser.py       # H264流解析器（关键帧检测）
│   └── monitoring.py        # 监控和统计模块
├── web_api/            # FastAPI RESTful API
│   ├── main.py              # FastAPI 应用入口
│   ├── dependencies.py      # 依赖注入
│   ├── auth.py              # 认证逻辑（bcrypt、session）
│   ├── routers/             # API 路由
│   │   ├── auth.py          # 认证路由（注册、登录）
│   │   ├── users.py         # 用户路由（用户信息、二维码）
│   │   └── admin.py         # Admin 路由（数据库查看、向量搜索）
│   └── models/              # Pydantic 数据模型
├── web_ui/              # React 前端
│   ├── src/
│   │   ├── components/      # React 组件
│   │   │   ├── Login.jsx           # 登录页面
│   │   │   ├── Register.jsx       # 注册页面
│   │   │   ├── UserDashboard.jsx  # 用户中心
│   │   │   ├── AdminDashboard.jsx # 数据库查看
│   │   │   ├── VectorSearch.jsx   # 向量搜索
│   │   │   ├── QRCode.jsx         # 二维码展示
│   │   │   └── Navbar.jsx         # 导航栏
│   │   ├── hooks/          # React Hooks
│   │   │   └── useAuth.js  # 认证状态管理
│   │   └── api/            # API 客户端
│   └── package.json        # 前端依赖
├── config/              # 配置模块
├── context/             # 动态上下文模块
│   ├── appearance_cache.py      # 人物外貌缓存管理器（并查集）
│   ├── event_context.py         # 事件上下文查询（从 JSONL 文件读取）
│   └── prompt_builder.py        # 动态提示词构建器
├── storage/             # 数据库存储
├── segmentation/        # 视频分段
├── video_processing/    # 视频理解
│   ├── qwen3_vl_processor.py        # 处理器工厂（根据环境变量选择 Flash/Plus）
│   ├── qwen3_vl_flash_processor.py  # Qwen3-VL Flash 处理器
│   └── qwen3_vl_plus_processor.py   # Qwen3-VL Plus 处理器
├── log_writer/          # 日志写入与加密
├── indexing/            # 分块与嵌入
│   ├── chunker.py              # 分块器（策略模式）
│   ├── chunking_strategies.py  # 分块策略实现
│   └── embedding_service.py    # 向量嵌入服务
├── orchestration/       # 流程编排
├── utils/               # 工具函数
│   └── segment_time_parser.py  # 分段时间解析工具函数
├── nginx/               # Nginx 配置
│   └── lab-log.conf     # Nginx 反向代理配置
├── scripts/             # 工具脚本
│   ├── process_video.py              # 视频处理入口（处理未分段视频）
│   ├── process_recording_session.py  # 处理已保存的采集会话（包含二维码结果）
│   ├── concat_videos.py              # 连接录制会话中的视频片段（重新编码并统一帧率）
│   ├── index_events.py              # 手动触发索引（分块和嵌入）
│   ├── end_of_day.py                # 日终处理脚本（外貌缓存压缩、加密入库、更新事件 person_ids）
│   ├── init_database.py             # 数据库初始化
│   ├── clear_test_data.py           # 清空测试数据
│   ├── test_segmentation.py         # 测试分段功能
│   ├── analyze_keyframes.py         # 分析关键帧
│   ├── extract_segment_aligned.py   # 对齐关键帧提取片段
│   └── test_vector_search.py        # 测试向量搜索
├── start.sh             # 启动脚本（后端+前端+Nginx）
├── stop.sh              # 停止脚本
└── logs_debug/          # 调试日志（JSONL 格式）
```

## 查看日志结果

### 1. 查看调试日志（JSONL 格式）

调试日志保存在 `logs_debug/event_logs.jsonl`，每行一个 JSON 对象：

```bash
# 查看所有日志
cat logs_debug/event_logs.jsonl

# 使用 jq 格式化查看（如果已安装）
cat logs_debug/event_logs.jsonl | jq .

# 查看最近 10 条日志
tail -n 10 logs_debug/event_logs.jsonl | jq .
```

### 2. 查询数据库

使用 MySQL 客户端连接 SeekDB：

```bash
mysql -h127.0.0.1 -uroot -P2881 -A lab_log
```

常用查询：

```sql
-- 查看所有事件日志
SELECT event_id, segment_id, start_time, end_time, raw_text 
FROM logs_raw 
ORDER BY start_time DESC 
LIMIT 20;

-- 查看结构化数据（JSON 格式）
-- 注意：字段名已从 encrypted_structured 改为 structured
SELECT event_id, structured 
FROM logs_raw 
WHERE event_id = 'your_event_id';

-- 查看日志分块和向量嵌入
SELECT chunk_id, chunk_text, start_time, end_time 
FROM logs_embedding 
ORDER BY start_time DESC 
LIMIT 10;

-- 查看关联的事件 ID
SELECT chunk_id, related_event_ids 
FROM logs_embedding;
```

### 3. 向量搜索

**使用 Python 脚本进行向量搜索**（推荐）：

```bash
# 使用测试脚本进行向量搜索
python scripts/test_vector_search.py
```

**使用 SQL 进行向量搜索**：

```sql
-- 示例：使用向量搜索（需要先准备查询向量）
-- 注意：实际使用时需要从 embedding_service 生成查询向量
SELECT 
    chunk_id,
    chunk_text,
    related_event_ids,
    start_time,
    end_time,
    cosine_distance(embedding, '[your_query_vector]') AS distance
FROM logs_embedding
ORDER BY distance
LIMIT 5;
```

**向量搜索说明**：
- 使用余弦距离（Cosine Distance）计算相似度
- 余弦距离衡量向量方向差异，与向量长度无关，更适合文本嵌入
- 距离越小（接近 0），相似度越高；距离越大（接近 2），相似度越低
- 支持语义搜索，可以找到语义相关的内容，即使关键词不完全匹配

### 4. 查看人物外貌缓存

人物外貌缓存保存在 `logs_debug/appearances_today.json`，可在 Cursor IDE 中打开查看。

```bash
# 查看外貌缓存（JSON 格式）
cat logs_debug/appearances_today.json | jq .

# 查看主记录数量
cat logs_debug/appearances_today.json | jq '.records | length'

# 查看并查集映射关系
cat logs_debug/appearances_today.json | jq '.union_find'
```

### 5. 全文搜索

```sql
-- 使用全文索引搜索
SELECT event_id, raw_text, 
       MATCH(raw_text) AGAINST('离心机' IN NATURAL LANGUAGE MODE) AS score
FROM logs_raw
WHERE MATCH(raw_text) AGAINST('离心机' IN NATURAL LANGUAGE MODE)
ORDER BY score DESC
LIMIT 10;
```

### 6. 查看二维码识别结果

二维码识别结果随 MP4 分段一起上报，格式为 `qr_results` 数组。每个结果包含：
- `user_id`：用户 ID（从二维码 JSON 中解析）
- `public_key_fingerprint`：公钥指纹（从二维码 JSON 中解析）
- `confidence`：置信度（基于二维码边界框面积）
- `detected_at_ms`：检测时间戳（毫秒，绝对时间）
- `detected_at`：检测时间戳（ISO 格式文本）

**在测试服务器中查看**：
```bash
# 启动测试服务器后，识别结果会直接打印到终端
python streaming_server/test_qr_server.py
```

**在流媒体服务器中查看**：
- 二维码识别结果会包含在 MP4 分段的元数据中
- 可以通过日志或数据库查询查看关联的用户信息

## 技术栈

### 后端

- **Python 3.10+**：主要开发语言
- **uv**：快速 Python 包管理工具
- **FastAPI**：现代、快速的 Web 框架，用于构建 API
- **SeekDB**：AI 原生混合搜索数据库（支持向量、全文、JSON）
- **Qwen3-VL Flash**：视频理解模型（DashScope API）
- **Qwen text-embedding-v4**：文本向量嵌入模型（1024 维）
- **ffmpeg/ffprobe**：视频处理和分段
- **Cryptography**：混合加密（AES-GCM + RSA-OAEP）
- **bcrypt**：密码哈希加密

### Android 采集端

- **Kotlin**：主要开发语言
- **CameraX**：相机框架，支持 Preview 和 ImageAnalysis
- **MediaCodec**：H.264 硬件编码
- **MediaMuxer**：MP4 封装
- **ML Kit Barcode Scanning**：二维码识别（版本 17.3.0+，支持 16KB 页面大小）
- **OkHttp**：WebSocket 客户端

### 前端

- **React**：用户界面库
- **Vite**：快速的前端构建工具
- **React Router**：客户端路由
- **Axios**：HTTP 客户端
- **WebCrypto API**：浏览器原生加密 API，用于生成密钥对

### 基础设施

- **Nginx**：反向代理服务器，统一前端和后端访问
- **Docker**：用于运行 SeekDB 容器

## 注意事项

1. **私钥安全**：
   - 测试用户的私钥保存在 `scripts/test_keys/`，请勿提交到版本控制系统
   - 用户注册时生成的私钥仅显示一次，请务必妥善保管
   - 私钥丢失后无法恢复，需要重新注册

2. **API Key**：确保 `DASHSCOPE_API_KEY` 有效且有足够的配额

3. **ffmpeg/ffprobe**：视频处理需要系统已安装 ffmpeg

4. **数据库连接**：确保 SeekDB 服务正在运行

5. **Nginx 配置**：
   - 启动脚本会自动配置 Nginx，但可能需要 root 权限
   - 如果自动配置失败，请手动复制 `nginx/lab-log.conf` 到 `/etc/nginx/conf.d/` 并重载 Nginx

6. **系统要求**：
   - 支持的系统：任何支持 Docker 的操作系统（Linux、macOS、Windows）
   - 最低配置：1 核 CPU，2GB 内存
   - 需要安装：
     - Docker（用于运行 SeekDB 容器）
     - Node.js 20+ 和 npm（用于前端）
     - Nginx（用于反向代理，可选但推荐）

7. **实时采集编码注意**：Android 端为每个关键帧前置完整 SPS/PPS（启用 `MediaFormat.KEY_PREPEND_HEADER_TO_SYNC_FRAMES`），保证分段 MP4 独立可解码，避免因缺少 PPS 导致封装/播放失败。

8. **字段名变更**：数据库字段名已从 `encrypted_structured` 改为 `structured`，新初始化的数据库使用新字段名

9. **二维码识别功能**：
   - Android 端使用 ML Kit 条码扫描（版本 17.3.0+，支持 16KB 页面大小）实时识别用户二维码
   - 二维码内容应为 JSON 格式，包含 `user_id` 和 `public_key_fingerprint` 字段
   - 识别结果按分段聚合，同一用户（基于 user_id + public_key_fingerprint）在同一分段内只保留置信度最高的结果
   - 识别结果随 MP4 分段元数据一起上报，格式为 `qr_results` 数组，包含 `user_id`、`public_key_fingerprint`、`confidence`、`detected_at_ms`、`detected_at` 字段
   - 识别成功时播放系统提示音并在预览层显示"已识别用户"提示

10. **动态上下文功能**：
    - 默认启用动态上下文模式（`DYNAMIC_CONTEXT_ENABLED=true`）
    - 每个录制会话维护独立的人物外貌缓存
    - 启动时自动加载已存在的外貌缓存文件（`logs_debug/appearances_today.json`），会继承上一次调试的结果
    - 事件上下文从 JSONL 文件（`logs_debug/event_logs.jsonl`）读取，无需数据库连接
    - 外貌缓存自动保存到 `logs_debug/appearances_today.json`（每处理 N 个分段）
    - 事件不加密直接写入数据库和 JSONL 文件，人物外貌表日终再加密入库
    - 使用 `scripts/end_of_day.py` 执行日终处理（压缩、加密、更新事件 person_ids）
    - 使用 `scripts/clear_test_data.py` 清空测试数据时，会同时清空事件日志文件和人物外貌缓存

11. **画面条纹问题解决经验**：
    - **问题现象**：竖屏采集时视频画面出现绿色/紫色条纹
    - **根本原因**：编码器输入色彩格式不匹配。某些设备（如 Pixel 6a）的硬件编码器实际使用 `COLOR_FormatYUV420Planar`（I420，分离 U/V 平面），而代码一直提供 NV12（半平面，交错 UV），导致 UV 平面错位
    - **解决方案**：
      1. 检测编码器实际输入色彩格式（从 MediaCodec outputFormat 获取）
      2. 如果为 Planar 格式，在送入编码器前将 NV12 转换为 I420
      3. 使用 CameraX 的实际帧时间戳（`image.imageInfo.timestamp`）而非固定间隔，确保视频时间轴准确
     4. 预览/取景使用显示方向的 `targetRotation`（Display rotation）；编码/采集使用物理方向+摄像头映射得到的 `rotationForBackend`，两者解耦，避免双重旋转或方向误判（实测竖直/左横/右横/倒置均与现实一致）
    - **关键代码**：`H264Encoder.encode()` 中根据 `encoderColorFormat` 动态选择 NV12 或 I420 格式
    - **额外收益**：使用真实帧时间戳后，视频 FPS 反映实际捕获速率（可能为非整数），播放速度与现实时间完美对齐

12. **16KB 页面大小兼容性**：
    - Android 15+ 要求所有原生库（.so 文件）对齐到 16KB 页面大小
    - ML Kit 17.3.0+ 已支持 16KB 对齐，使用该版本可避免兼容性警告
    - 在 `build.gradle.kts` 中设置 `packaging.jniLibs.useLegacyPackaging = false` 确保正确打包
13. **WebSocket 分段过大导致客户端自停**：
    - 现象：60s 分段在 1920x1920 @4fps，2MB 码率下单段约 12.8MB，Base64 后约 16.3MB，超过 OkHttp 客户端 WebSocket 发送队列硬上限（16MB），`send()` 返回 false，App 发送 error/capture_stopped 后断开
    - 根因：客户端发送队列 16MB 硬限制，与服务器端 `WEBSOCKET_MAX_SIZE_MB` 无关
    - 解决方案：降低单段体积，让 Base64 长度 <~15.5MB（约等于 MP4 <~11.6MB）
      1) 缩短分段时长（例如 60s→30s）
      2) 降低码率（实测 1MB 码率、60s 段约 6.9MB MP4，Base64 8.7MB，正常发送）
      3) 降低分辨率或帧率

