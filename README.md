# 视频日志系统 MVP 使用说明

## 项目背景

本项目是一个**实验室视觉日志系统**的 MVP（最小可行产品）实现。系统的核心目标是通过相机和视觉大模型，将实验室内的人物动作（使用设备和药品等）和设备运转状态自动记录为结构化文本日志，为更高级的智能体应用和 AI 实验室管家奠定基础。

### 核心特性

- **视频理解**：使用 Qwen3-VL Plus 视觉大模型分析实验室视频，自动识别人物动作、设备操作等信息
- **结构化日志**：将视频内容转换为带时间戳的结构化事件日志
- **字段级加密**：支持对敏感字段（如人物外观特征）进行加密，使用混合加密方案（AES-GCM + RSA-OAEP）
- **向量检索**：支持日志的向量嵌入和语义搜索，便于后续的智能查询和分析

### 系统架构

系统采用模块化设计，主要包含以下模块：

- **视频接入**：支持 MP4 视频文件处理（未来可扩展为流式处理）
- **视频分段**：使用关键帧对齐将长视频分割为处理段（约 60 秒），支持迭代式分段确保连续性
- **视频理解**：调用 Qwen3-VL Plus API 进行视频内容分析
- **日志写入**：将识别的事件写入数据库，并对敏感字段进行加密
- **向量嵌入**：对日志进行分块和向量化，支持语义搜索
- **存储**：使用 SeekDB 作为数据库，支持关系型、向量和全文搜索

## 工作流程

### 整体流程

```
视频文件 (MP4)
    ↓
[视频分段] 关键帧对齐，分为多个约 60 秒的片段（迭代式分段确保连续性）
    ↓
[视频理解] 对每个片段调用 Qwen3-VL Plus，提取事件
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

### 数据流

1. **视频分段**：
   - 使用 ffprobe 检测所有关键帧（I 帧）位置
   - 以关键帧为边界进行分段，每个分段约 60 秒
   - 采用迭代式分段：每提取一个分段后，检查实际结束时间，从那里开始下一个分段
   - 确保分段连续且无重叠，每个分段不超过 5 分钟
2. **视频理解**：
   - 调用 Qwen3-VL Plus API 分析视频内容
   - 提取人物动作、设备操作、时间戳等信息
   - 生成结构化的事件列表（EventLog）
3. **日志加密**（如启用）：
   - 对敏感字段（如 `person.clothing_color`）使用 AES-256-GCM 加密
   - 使用用户 RSA 公钥加密数据加密密钥（DEK）
   - 将加密后的字段和 DEK 分别存储
4. **数据存储**：
   - 写入 SeekDB 的 `logs_raw` 表（包含加密后的结构化数据）
   - 同时写入 `logs_debug/event_logs.jsonl` 用于调试
5. **索引构建**（可选）：
   - 使用配置的分块策略聚合事件日志（默认：每个事件一个块）
   - 生成文本向量嵌入（Qwen text-embedding-v4，1024 维）
   - 写入 `logs_embedding` 表，支持后续的向量搜索

## 快速开始

### 1. 部署 SeekDB

本项目使用 Docker 部署 SeekDB。使用以下命令启动 SeekDB 容器：

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

**验证部署**：

```bash
# 检查容器状态
docker ps | grep seekdb

# 查看容器日志
docker logs seekdb

# 测试连接（需要安装 obclient 或 MySQL 客户端）
mysql -h127.0.0.1 -uroot -P2881
```

**停止和重启**：

```bash
# 停止容器
docker stop seekdb

# 启动容器
docker start seekdb

# 删除容器（数据会丢失）
docker rm -f seekdb
```

### 2. 配置环境变量

创建 `.env` 文件：

```bash
# DashScope API Key（用于 Qwen3-VL 和 embedding）
DASHSCOPE_API_KEY=your_api_key_here

# 加密配置（可选）
ENCRYPTION_ENABLED=true
ENCRYPTION_TEST_USER_ID=admin

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

### 4. 安装 Python 依赖

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

### 5. 处理视频

```bash
# 如果使用虚拟环境，先激活（或直接使用 .venv/bin/python）
source .venv/bin/activate
python scripts/process_video.py /path/to/video.mp4

# 或者不激活，直接使用虚拟环境的 Python
.venv/bin/python scripts/process_video.py /path/to/video.mp4
```

可选参数：
- `--no-indexing`: 禁用索引（分块和嵌入），只写入日志

### 6. 工具脚本

项目提供了多个工具脚本用于测试和调试：

```bash
# 测试分段功能（不调用大模型）
python scripts/test_segmentation.py <视频文件路径>

# 分析视频关键帧位置和间隔
python scripts/analyze_keyframes.py <视频文件1> [视频文件2] ...

# 从视频中提取片段（自动对齐到关键帧）
python scripts/extract_segment_aligned.py <视频文件> <起始时间> <结束时间> <输出文件>

# 测试向量搜索功能
python scripts/test_vector_search.py

# 清空测试数据
python scripts/clear_test_data.py
```

## 功能说明

### 视频分段
- **关键帧对齐**：优先使用关键帧（I 帧）作为分段边界
- **迭代式分段**：每提取一个分段后，检查实际结束时间，从那里开始下一个分段，确保连续且无重叠
- **目标段长**：约 60 秒，但会根据关键帧位置自动调整
- **最大段长限制**：每个分段不超过 5 分钟，确保发送给大模型的视频不会过长
- **回退机制**：如果关键帧太少，自动回退到时间分段

### 视频理解
- 使用 Qwen3-VL Plus 进行视频理解
- 自动提取人物动作、设备操作等信息
- 从视频画面提取时间戳

### 日志加密
- 字段级加密（混合加密：AES-GCM + RSA-OAEP）
- 默认加密字段：`person.clothing_color`, `person.hair_color`
- 可通过 `config/encryption_config.py` 配置

### 日志分块与嵌入
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
├── config/              # 配置模块
├── storage/             # 数据库存储
├── segmentation/        # 视频分段
├── video_processing/    # 视频理解
├── log_writer/          # 日志写入与加密
├── indexing/            # 分块与嵌入
│   ├── chunker.py              # 分块器（策略模式）
│   ├── chunking_strategies.py  # 分块策略实现
│   └── embedding_service.py    # 向量嵌入服务
├── orchestration/       # 流程编排
├── scripts/             # 工具脚本
│   ├── process_video.py         # 视频处理入口
│   ├── init_database.py         # 数据库初始化
│   ├── clear_test_data.py        # 清空测试数据
│   ├── test_segmentation.py     # 测试分段功能
│   ├── analyze_keyframes.py     # 分析关键帧
│   ├── extract_segment_aligned.py  # 对齐关键帧提取片段
│   └── test_vector_search.py    # 测试向量搜索
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
SELECT event_id, encrypted_structured 
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

### 4. 全文搜索

```sql
-- 使用全文索引搜索
SELECT event_id, raw_text, 
       MATCH(raw_text) AGAINST('离心机' IN NATURAL LANGUAGE MODE) AS score
FROM logs_raw
WHERE MATCH(raw_text) AGAINST('离心机' IN NATURAL LANGUAGE MODE)
ORDER BY score DESC
LIMIT 10;
```

## 技术栈

- **Python 3.10+**：主要开发语言
- **uv**：快速 Python 包管理工具
- **SeekDB**：AI 原生混合搜索数据库（支持向量、全文、JSON）
- **Qwen3-VL Plus**：视频理解模型（DashScope API）
- **Qwen text-embedding-v4**：文本向量嵌入模型（1024 维）
- **ffmpeg/ffprobe**：视频处理和分段
- **Cryptography**：混合加密（AES-GCM + RSA-OAEP）

## 注意事项

1. **私钥安全**：测试用户的私钥保存在 `scripts/test_keys/`，请勿提交到版本控制系统
2. **API Key**：确保 `DASHSCOPE_API_KEY` 有效且有足够的配额
3. **ffmpeg/ffprobe**：视频处理需要系统已安装 ffmpeg
4. **数据库连接**：确保 SeekDB 服务正在运行
5. **系统要求**：
   - 支持的系统：任何支持 Docker 的操作系统（Linux、macOS、Windows）
   - 最低配置：1 核 CPU，2GB 内存
   - 需要安装 Docker（用于运行 SeekDB 容器）

