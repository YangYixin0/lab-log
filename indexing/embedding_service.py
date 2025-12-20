"""向量嵌入服务（Qwen text-embedding-v4）"""

import os
from typing import List

from dotenv import load_dotenv
import dashscope

# 加载环境变量
load_dotenv()


class EmbeddingService:
    """向量嵌入服务"""
    
    def __init__(self, api_key: str = None, model: str = "text-embedding-v4", dimensions: int = 1024):
        """
        初始化嵌入服务
        
        Args:
            api_key: DashScope API Key，如果为 None 则从环境变量读取
            model: 模型名称，默认 text-embedding-v4
            dimensions: 向量维度，默认 1024
        """
        self.api_key = api_key or os.getenv('DASHSCOPE_API_KEY')
        if not self.api_key:
            raise ValueError("未提供 DASHSCOPE_API_KEY，请在环境变量或参数中设置")
        
        self.model = model
        self.dimensions = dimensions
    
    def embed_text(self, text: str) -> List[float]:
        """
        生成文本向量（Qwen text-embedding-v4, 1024 维）
        
        Args:
            text: 要嵌入的文本
        
        Returns:
            向量列表（1024 维浮点数列表）
        """
        try:
            response = dashscope.TextEmbedding.call(
                model=self.model,
                input=text,
                text_type='document',
                api_key=self.api_key
            )
            
            # 解析响应
            if response.status_code == 200:
                embeddings = response.output.get('embeddings', [])
                if embeddings and len(embeddings) > 0:
                    embedding = embeddings[0].get('embedding', [])
                    # 如果维度不匹配，截断或填充
                    if len(embedding) != self.dimensions:
                        if len(embedding) > self.dimensions:
                            embedding = embedding[:self.dimensions]
                        else:
                            embedding = embedding + [0.0] * (self.dimensions - len(embedding))
                    return embedding
                else:
                    raise RuntimeError("API 返回的嵌入向量为空")
            else:
                raise RuntimeError(f"API 调用失败: {response.message}")
        except Exception as e:
            raise RuntimeError(f"生成向量嵌入失败: {e}")
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成文本向量
        
        Args:
            texts: 文本列表
        
        Returns:
            向量列表（每个文本对应一个向量）
        """
        try:
            response = dashscope.TextEmbedding.call(
                model=self.model,
                input=texts,
                text_type='document',
                api_key=self.api_key
            )
            
            # 解析响应
            if response.status_code == 200:
                embeddings = response.output.get('embeddings', [])
                result = []
                for item in embeddings:
                    embedding = item.get('embedding', [])
                    # 如果维度不匹配，截断或填充
                    if len(embedding) != self.dimensions:
                        if len(embedding) > self.dimensions:
                            embedding = embedding[:self.dimensions]
                        else:
                            embedding = embedding + [0.0] * (self.dimensions - len(embedding))
                    result.append(embedding)
                return result
            else:
                raise RuntimeError(f"API 调用失败: {response.message}")
        except Exception as e:
            raise RuntimeError(f"批量生成向量嵌入失败: {e}")

