# 实验室日志系统 MVP 架构说明

> 本文档用于指导 MVP 阶段的工程实现，重点在于 **日志写入全流程** 的稳定性、可扩展性与可替换性。视频理解模型、前端形态均视为可演进组件。

---

## 1. 系统目标与边界

### 1.1 MVP 核心目标

- 从**连续视频（MP4）**中，自动生成**带时间戳的结构化子日志**
- 支持字段级加密与用户授权解密
- 支持日志分块、嵌入与基于日志的解读（作为示例应用）
- 架构上支持：
  - 视频处理模块可替换
  - 日志应用可扩展

### 1.2 非目标（MVP 不做）

- 不追求人物身份识别、一致性识别
- 不追求实时处理
- 不做复杂权限系统（RBAC / OAuth 等）

---

## 2. 顶层模块划分

```
lab-log-system/
├── ingest/                 # 视频接入（当前阶段 MP4 / 未来 流式）
├── segmentation/           # 视频分段
├── video_processing/       # 视频理解（可替换）
├── log_writer/             # 日志生成 + 字段级加密（核心）
├── storage/                # 数据库存储抽象（SeekDB）
├── indexing/               # 分块与向量嵌入
├── user_management/        # 用户、密钥、公钥管理
├── ticketing/              # 日志解读工单系统
├── log_reader/             # 日志解读 Agent（示例应用）
├── orchestration/          # LangGraph / 流程编排
├── api/                    # HTTP API
├── web_ui/                 # Web 前端（注册 / 解密 / 工单）
└── logs_debug/             # 人类可读日志文件（调试）
```

---

## 3. 视频处理与日志写入流程

### 3.1 视频分段（Segmentation）

- 输入：完整 MP4 文件
- 策略：
  - GOP 对齐
  - 目标段长 ≈ 60s，允许大幅浮动
- 每个分段即一个 **处理段（Processing Segment）**

```python
class VideoSegment:
    segment_id: str
    video_path: str
    start_time: float   # seconds in video
    end_time: float
```

---

### 3.2 视频理解接口（可替换）

视频处理模块只需遵守统一接口：

```python
class VideoUnderstandingResult:
    segment_id: str
    remark: str
    events: list["EventLog"]
```

事件由视觉模型自行决定是否生成。

---

### 3.3 子日志（EventLog）定义

每一个“事件”生成一条子日志，是系统最小原子。

```python
class EventLog:
    event_id: str
    segment_id: str
    start_time: datetime   # 来自画面水印
    end_time: datetime
    structured: dict       # 固定 schema
    raw_text: str
```

#### 3.3.1 structured schema（示例）

```json
{
  "person": {
    "present": true,
    "clothing_color": "<encrypted>"
  },
  "action": "operating centrifuge",
  "remark": "optional free text"
}
```

- schema 稳定
- 允许 `remark` 字段用于扩展

---

## 4. 日志写入与加密设计

### 4.1 加密粒度

- 字段级加密（MVP 示例：`person.clothing_color`）
- 使用用户公钥加密字段内容

```python
encrypted_value = encrypt(value, user_public_key)
```

### 4.2 写入策略

- **每条子日志生成后：**
  - 写入传统数据库（SeekDB）
  - 同时写入 `logs_debug/` 下的 JSONL 文件
- 文件仅用于调试与人工查看

---

## 5. 存储抽象（SeekDB）

### 5.1 核心表（逻辑）

#### logs_raw
- event_id
- start_time
- end_time
- encrypted_structured (JSON)
- raw_text

#### logs_embedding（凌晨生成）
- chunk_id
- embedding
- related_event_ids

---

## 6. 分块与嵌入（Indexing）

### 6.1 运行方式

- **生产环境**：每日凌晨定时任务
- **测试环境**：手动触发

### 6.2 分块策略（MVP）

- 按时间（如 5–10 分钟）聚合子日志
- 拼接 raw_text 生成 chunk_text
- 生成 embedding 并写入向量表

---

## 7. 日志解读与工单系统

### 7.1 工单（Ticket）模型

```python
class Ticket:
    ticket_id: str
    query: str
    requester_id: str
    status: Literal[
        "CREATED",
        "WAITING_AUTH",
        "AUTH_GRANTED",
        "AUTH_REJECTED",
        "CANCELLED",
        "PROCESSING",
        "DONE"
    ]
```

---

### 7.2 解密与等待机制

- Agent 判断查询涉及加密字段 → 进入 `WAITING_AUTH`
- 发起解密请求给相关用户
- **提问用户可以选择：**
  - 等待解密结果
  - 主动取消（Ticket → CANCELLED）

### 7.3 解密许可到达后的行为

- 若 Ticket 仍处于 `WAITING_AUTH`：
  - 系统自动激活 Agent
  - 解密相关日志
  - 进入 `PROCESSING → DONE`

---

## 8. LogSource 抽象（统一访问）

日志解读模块通过统一接口访问日志：

```python
class LogSource:
    def query(time_range, filters) -> list[EventLog]
```

实现：
- `DatabaseLogSource`
- （可选）`FileLogSource`（调试）

---

## 9. 用户管理与密钥

### 9.1 用户注册

- Web 前端生成密钥对（WebCrypto）
- 公钥上传至后端
- 私钥仅保存在用户侧

### 9.2 解密流程

1. 后端发送解密请求
2. 用户确认
3. 用户端解密字段或 DEK
4. 返回明文或临时解密结果

---

## 10. Web 前端（MVP）

### 功能范围

- 用户注册 / 登录
- 展示用户二维码（身份 + 公钥指纹）
- 查看待处理解密请求（同意 / 拒绝）
- 查看自己发起的解读工单及状态

### 技术建议

- React + Vite
- 不做 SSR
- 不引入复杂状态管理

---

## 11. LangGraph / 编排

### 11.1 写日志流程（串行）

```
MP4 → 分段 → 视频理解 → 子日志生成 → 加密 → DB + 文件
```

### 11.2 解读流程（异步）

```
Query → 检索 → 是否需解密？
        ├─ 否 → 直接回答
        └─ 是 → 创建工单 → 等待 → 解密 → 回答
```

---

## 12. 设计原则总结

- 日志是平台能力，不是某个 Agent 的副产品
- 写日志同步、确定；读日志异步、可等待
- 所有模块围绕“子日志”这一最小原子构建
- MVP 重在结构正确，而非模型聪明

