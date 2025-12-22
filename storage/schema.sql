-- SeekDB 数据库表结构定义

-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS lab_log CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE lab_log;

-- ==================== 用户管理 ====================
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    public_key_pem TEXT NOT NULL COMMENT 'RSA 公钥（PEM 格式）',
    password_hash VARCHAR(255) COMMENT 'bcrypt 哈希密码（可选，支持公钥登录的用户可为 NULL）',
    role ENUM('admin', 'user') DEFAULT 'user' COMMENT '用户角色',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==================== 核心日志表 ====================
CREATE TABLE IF NOT EXISTS logs_raw (
    event_id VARCHAR(64) PRIMARY KEY,
    segment_id VARCHAR(64) NOT NULL,
    start_time DATETIME NOT NULL COMMENT '事件开始时间（来自画面水印）',
    end_time DATETIME NOT NULL COMMENT '事件结束时间',
    event_type VARCHAR(32) COMMENT '事件类型，如 "person"、"equipment-only"',
    structured JSON COMMENT '结构化数据（字段级加密）',
    raw_text TEXT COMMENT '明文文本（用于检索和嵌入）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_segment (segment_id),
    INDEX idx_time (start_time, end_time),
    INDEX idx_event_type (event_type),
    FULLTEXT INDEX idx_fts_text (raw_text) WITH PARSER ik COMMENT '全文索引'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==================== 字段加密密钥表（DEK 管理）====================
-- 每个需要加密的字段，对每个有权限的用户，存储一份用该用户公钥加密的 DEK
CREATE TABLE IF NOT EXISTS field_encryption_keys (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL,
    field_path VARCHAR(255) NOT NULL COMMENT 'JSON 路径，例如 person.clothing_color',
    user_id VARCHAR(64) NOT NULL COMMENT '这个 DEK 对应的用户',
    encrypted_dek TEXT NOT NULL COMMENT '用用户 RSA 公钥加密的 DEK（Base64 编码）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_event_field_user (event_id, field_path, user_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_event (event_id),
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==================== 向量嵌入表 ====================
CREATE TABLE IF NOT EXISTS logs_embedding (
    chunk_id VARCHAR(64) PRIMARY KEY,
    embedding VECTOR(1024) COMMENT 'Qwen text-embedding-v4, 1024 维向量',
    chunk_text TEXT COMMENT '分块文本内容',
    related_event_ids JSON COMMENT '关联的 event_id 数组',
    start_time DATETIME COMMENT 'chunk 的时间范围开始',
    end_time DATETIME COMMENT 'chunk 的时间范围结束',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    VECTOR INDEX idx_vec (embedding) WITH(DISTANCE=cosine, TYPE=hnsw, LIB=vsag) COMMENT '向量索引'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==================== 工单表 ====================
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id VARCHAR(64) PRIMARY KEY,
    query TEXT NOT NULL COMMENT '用户查询',
    requester_id VARCHAR(64) COMMENT '请求者用户 ID',
    status ENUM('CREATED', 'WAITING_AUTH', 'AUTH_GRANTED', 'AUTH_REJECTED', 
                'CANCELLED', 'PROCESSING', 'DONE') DEFAULT 'CREATED',
    result TEXT COMMENT 'Agent 生成的回答',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (requester_id) REFERENCES users(user_id),
    INDEX idx_status (status),
    INDEX idx_requester (requester_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

