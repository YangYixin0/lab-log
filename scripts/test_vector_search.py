#!/usr/bin/env python3
"""测试向量搜索功能"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from storage.seekdb_client import SeekDBClient
from indexing.embedding_service import EmbeddingService
import json


def test_vector_search():
    """测试向量搜索"""
    print("=" * 70)
    print("向量搜索测试")
    print("=" * 70)
    
    # 初始化服务
    db_client = SeekDBClient()
    embedding_service = EmbeddingService()
    
    # 测试查询
    test_queries = [
        "操作仪器",
        "人员进入",
        "操作手机",
        "操作电脑",
        "无人员活动"
    ]
    
    for query_text in test_queries:
        print(f"\n查询: {query_text}")
        print("-" * 70)
        
        try:
            # 1. 生成查询向量
            print("  生成查询向量...")
            query_vector = embedding_service.embed_text(query_text)
            print(f"  向量维度: {len(query_vector)}")
            
            # 2. 执行向量搜索
            print("  执行向量搜索...")
            cursor = db_client.connection.cursor()
            
            # 将向量转换为 JSON 字符串格式
            vector_json = json.dumps(query_vector)
            
            # 使用余弦距离进行向量搜索
            sql = f"""
                SELECT 
                    chunk_id,
                    chunk_text,
                    related_event_ids,
                    start_time,
                    end_time,
                    cosine_distance(embedding, '{vector_json}') AS distance
                FROM logs_embedding
                ORDER BY distance
                LIMIT 5
            """
            
            cursor.execute(sql)
            results = cursor.fetchall()
            
            print(f"  找到 {len(results)} 个最相似的分块:\n")
            
            for i, row in enumerate(results, 1):
                chunk_id = row['chunk_id']
                chunk_text = row['chunk_text']
                related_event_ids = row['related_event_ids']
                start_time = row['start_time']
                end_time = row['end_time']
                distance = float(row['distance']) if row['distance'] else None
                
                print(f"  {i}. 分块 {chunk_id}")
                print(f"     距离: {distance:.6f}" if distance is not None else "     距离: N/A")
                print(f"     文本: {chunk_text[:60]}...")
                print(f"     时间: {start_time} - {end_time}")
                print(f"     关联事件: {related_event_ids}")
                print()
            
            cursor.close()
            
        except Exception as e:
            print(f"  ✗ 搜索失败: {e}")
            import traceback
            traceback.print_exc()
    
    db_client.connection.close()
    print("=" * 70)
    print("测试完成")
    print("=" * 70)


if __name__ == '__main__':
    test_vector_search()

