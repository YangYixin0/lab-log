"""加密配置模块"""

import os
from typing import Set


class EncryptionConfig:
    """加密配置"""
    
    # 全局加密开关（环境变量：ENCRYPTION_ENABLED=true/false）
    ENABLED: bool = os.getenv("ENCRYPTION_ENABLED", "true").lower() == "true"
    
    # 需要加密的字段路径列表（JSON 路径）
    ENCRYPTED_FIELDS: Set[str] = {
        "person.clothing_color",
        "person.hair_color",
        # 可以扩展更多字段
    }
    
    # 测试用户 ID（用于测试阶段统一加密）
    TEST_USER_ID: str = os.getenv("ENCRYPTION_TEST_USER_ID", "admin")
    
    @classmethod
    def is_field_encrypted(cls, field_path: str) -> bool:
        """判断字段是否需要加密"""
        if not cls.ENABLED:
            return False
        return field_path in cls.ENCRYPTED_FIELDS
    
    @classmethod
    def should_encrypt(cls) -> bool:
        """全局是否启用加密"""
        return cls.ENABLED

