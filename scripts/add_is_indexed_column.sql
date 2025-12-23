-- 为 logs_raw 表添加 is_indexed 字段的迁移脚本
-- 如果字段已存在，此脚本会失败，需要手动处理

USE lab_log;

-- 添加 is_indexed 字段
ALTER TABLE logs_raw 
ADD COLUMN is_indexed BOOLEAN DEFAULT FALSE COMMENT '是否经过分块嵌入处理' AFTER raw_text;

-- 添加索引以提高查询性能
ALTER TABLE logs_raw 
ADD INDEX idx_is_indexed (is_indexed);

-- 将现有记录标记为未索引（如果之前没有索引过）
-- 注意：如果之前已经索引过，需要根据实际情况手动更新
-- UPDATE logs_raw SET is_indexed = FALSE WHERE is_indexed IS NULL;

