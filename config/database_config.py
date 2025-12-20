"""数据库配置模块"""

import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class DatabaseConfig:
    """数据库配置"""
    
    # SeekDB 连接配置
    HOST: str = os.getenv("SEEKDB_HOST", "127.0.0.1")
    PORT: int = int(os.getenv("SEEKDB_PORT", "2881"))
    DATABASE: str = os.getenv("SEEKDB_DATABASE", "lab_log")
    USER: str = os.getenv("SEEKDB_USER", "root")
    PASSWORD: str = os.getenv("SEEKDB_PASSWORD", "")
    
    @classmethod
    def get_connection_string(cls) -> dict:
        """获取数据库连接参数字典"""
        return {
            "host": cls.HOST,
            "port": cls.PORT,
            "database": cls.DATABASE,
            "user": cls.USER,
            "password": cls.PASSWORD,
        }

