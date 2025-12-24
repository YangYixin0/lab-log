#!/usr/bin/env python3
"""手动索引事件脚本：对未索引的事件进行分块和嵌入"""

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from storage.seekdb_client import SeekDBClient
from storage.models import EventLog
from indexing.chunker import LogChunker
from indexing.embedding_service import EmbeddingService
from datetime import datetime


def parse_event_from_db(row: Dict[str, Any]) -> EventLog:
    """从数据库行转换为 EventLog 对象"""
    import json
    
    # 解析 structured JSON
    structured = row['structured']
    if isinstance(structured, str):
        structured = json.loads(structured)
    
    return EventLog(
        event_id=row['event_id'],
        segment_id=row['segment_id'],
        start_time=row['start_time'],
        end_time=row['end_time'],
        event_type=row.get('event_type'),
        structured=structured,
        raw_text=row.get('raw_text', '')
    )


def main():
    parser = argparse.ArgumentParser(description='对未索引的事件进行分块和嵌入')
    parser.add_argument('--limit', type=int, default=1000, help='一次处理的最大事件数量（默认1000）')
    parser.add_argument('--batch-size', type=int, default=100, help='批量处理的事件数量（默认100）')
    
    args = parser.parse_args()
    
    db_client = SeekDBClient()
    chunker = LogChunker()
    embedding_service = EmbeddingService()
    
    try:
        print(f"开始索引事件（每次最多处理 {args.limit} 个事件，批量大小 {args.batch_size}）...")
        
        total_processed = 0
        total_chunks = 0
        total_success = 0
        total_failed = 0
        
        while True:
            # 获取未索引的事件
            unindexed_events = db_client.get_unindexed_events(limit=args.limit)
            
            if not unindexed_events:
                print("没有未索引的事件了")
                break
            
            print(f"\n获取到 {len(unindexed_events)} 个未索引事件，开始处理...")
            
            # 转换为 EventLog 对象
            events = [parse_event_from_db(row) for row in unindexed_events]
            
            # 分批处理
            for batch_start in range(0, len(events), args.batch_size):
                batch_events = events[batch_start:batch_start + args.batch_size]
                batch_num = batch_start // args.batch_size + 1
                total_batches = (len(events) + args.batch_size - 1) // args.batch_size
                
                print(f"\n处理批次 {batch_num}/{total_batches}（{len(batch_events)} 个事件）...")
                
                try:
                    # 分块
                    chunks = chunker.chunk_events(batch_events)
                    print(f"  生成 {len(chunks)} 个分块")
                    
                    if not chunks:
                        # 如果没有分块，直接标记为已索引
                        event_ids = [e.event_id for e in batch_events]
                        db_client.mark_events_as_indexed(event_ids)
                        total_processed += len(batch_events)
                        print(f"  无分块，已标记 {len(batch_events)} 个事件为已索引")
                        continue
                    
                    # 为每个分块生成嵌入并写入数据库
                    batch_success = 0
                    batch_failed = 0
                    processed_event_ids = set()
                    
                    for i, chunk in enumerate(chunks, 1):
                        try:
                            # 生成嵌入
                            embedding = embedding_service.embed_text(chunk.chunk_text)
                            chunk.embedding = embedding
                            
                            # 写入数据库
                            db_client.insert_log_chunk(
                                chunk_id=chunk.chunk_id,
                                chunk_text=chunk.chunk_text,
                                related_event_ids=chunk.related_event_ids,
                                embedding=embedding,
                                start_time=chunk.start_time.isoformat(),
                                end_time=chunk.end_time.isoformat()
                            )
                            
                            # 收集已处理的事件 ID
                            processed_event_ids.update(chunk.related_event_ids)
                            batch_success += 1
                            
                            if i % 10 == 0:
                                print(f"  已处理 {i}/{len(chunks)} 个分块")
                        except Exception as e:
                            batch_failed += 1
                            print(f"  处理分块失败 ({chunk.chunk_id}): {e}")
                            import traceback
                            traceback.print_exc()
                            continue
                    
                    # 标记所有相关事件为已索引
                    if processed_event_ids:
                        event_ids_list = list(processed_event_ids)
                        db_client.mark_events_as_indexed(event_ids_list)
                        print(f"  已标记 {len(event_ids_list)} 个事件为已索引")
                    
                    total_processed += len(batch_events)
                    total_chunks += len(chunks)
                    total_success += batch_success
                    total_failed += batch_failed
                    
                    print(f"  批次完成：成功 {batch_success} 个分块，失败 {batch_failed} 个分块")
                    
                except Exception as e:
                    print(f"  批次处理失败: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            # 如果获取的事件数量少于 limit，说明已经处理完了
            if len(unindexed_events) < args.limit:
                break
        
        print(f"\n索引完成！")
        print(f"  处理事件数: {total_processed}")
        print(f"  生成分块数: {total_chunks}")
        print(f"  成功分块数: {total_success}")
        print(f"  失败分块数: {total_failed}")
        
    except Exception as e:
        print(f"索引失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db_client.close()


if __name__ == '__main__':
    main()


