"""主处理流程（串行执行）"""

from typing import List, Optional

from segmentation.segmenter import VideoSegmenter
from video_processing.interface import VideoProcessor
from video_processing.qwen3_vl_processor import Qwen3VLProcessor
from log_writer.writer import LogWriter
from indexing.chunker import LogChunker
from indexing.embedding_service import EmbeddingService
from storage.seekdb_client import SeekDBClient
from storage.models import EventLog


class VideoLogPipeline:
    """视频日志处理流程"""
    
    def __init__(self, 
                 video_processor: Optional[VideoProcessor] = None,
                 log_writer: Optional[LogWriter] = None,
                 chunker: Optional[LogChunker] = None,
                 embedding_service: Optional[EmbeddingService] = None,
                 db_client: Optional[SeekDBClient] = None,
                 enable_indexing: bool = False):
        """
        初始化处理流程
        
        Args:
            video_processor: 视频处理器，如果为 None 则创建默认的 Qwen3VLProcessor
            log_writer: 日志写入器，如果为 None 则创建默认实例
            chunker: 日志分块器，如果为 None 则创建默认实例
            embedding_service: 嵌入服务，如果为 None 则创建默认实例
            db_client: 数据库客户端，如果为 None 则创建默认实例
            enable_indexing: 是否启用索引（分块和嵌入），默认 False（已废弃，索引完全由独立脚本处理，不再由视频处理触发）
        """
        self.db_client = db_client or SeekDBClient()
        
        self.video_processor = video_processor or Qwen3VLProcessor()
        self.log_writer = log_writer or LogWriter(self.db_client)
        self.chunker = chunker or LogChunker()
        self.embedding_service = embedding_service or EmbeddingService()
        self.enable_indexing = enable_indexing  # 保留参数以兼容旧代码，但实际不再使用
    
    def process_video(self, video_path: str) -> List[EventLog]:
        """
        处理视频：分段 → 理解并立即写入
        
        Args:
            video_path: 视频文件路径
        
        Returns:
            所有生成的事件日志列表
        """
        print(f"开始处理视频: {video_path}")
        
        # 1. 视频分段
        print("步骤 1/2: 视频分段...")
        segmenter = VideoSegmenter()
        segments = segmenter.segment(video_path)
        print(f"  分段完成，共 {len(segments)} 个分段")
        
        # 2. 视频理解并立即写入
        from config.encryption_config import EncryptionConfig
        encryption_status = "（加密）" if EncryptionConfig.should_encrypt() else ""
        print(f"步骤 2/2: 视频理解并写入日志{encryption_status}...")
        all_events = []
        total_written = 0
        for i, segment in enumerate(segments, 1):
            print(f"  处理分段 {i}/{len(segments)}: {segment.segment_id}")
            try:
                # 视频理解
                result = self.video_processor.process_segment(segment)
                print(f"    识别到 {len(result.events)} 个事件")
                
                # 立即写入日志（每理解一段就立刻写入）
                for event in result.events:
                    try:
                        self.log_writer.write_event_log(event)
                        total_written += 1
                    except Exception as e:
                        print(f"    写入事件失败 ({event.event_id}): {e}")
                        continue
                
                # 收集事件（用于返回值）
                all_events.extend(result.events)
                print(f"    已写入 {len(result.events)} 个事件到数据库")
            except Exception as e:
                print(f"    处理分段失败: {e}")
                continue
        
        print(f"  视频处理完成，共识别 {len(all_events)} 个事件，已写入 {total_written} 个事件")
        print("视频处理完成！")
        return all_events
    
    def index_events(self, events: List[EventLog]) -> dict:
        """
        对事件进行分块和嵌入（公共方法，供实时处理流程调用）
        
        Args:
            events: 要索引的事件列表
        
        Returns:
            包含索引结果的字典：{'chunks': 分块数量, 'success': 成功数量, 'failed': 失败数量}
        """
        if not self.enable_indexing or not events:
            return {'chunks': 0, 'success': 0, 'failed': 0}
        
        # 分块
        chunks = self.chunker.chunk_events(events)
        
        if not chunks:
            # 如果没有分块，直接标记所有事件为已索引
            event_ids = [e.event_id for e in events]
            if event_ids:
                self.db_client.mark_events_as_indexed(event_ids)
            return {'chunks': 0, 'success': 0, 'failed': 0}
        
        # 为每个分块生成嵌入并写入数据库
        success_count = 0
        failed_count = 0
        processed_event_ids = set()
        
        for chunk in chunks:
            try:
                # 生成嵌入
                embedding = self.embedding_service.embed_text(chunk.chunk_text)
                chunk.embedding = embedding
                
                # 写入数据库
                self.db_client.insert_log_chunk(
                    chunk_id=chunk.chunk_id,
                    chunk_text=chunk.chunk_text,
                    related_event_ids=chunk.related_event_ids,
                    embedding=embedding,
                    start_time=chunk.start_time.isoformat(),
                    end_time=chunk.end_time.isoformat()
                )
                
                # 收集已处理的事件 ID
                processed_event_ids.update(chunk.related_event_ids)
                success_count += 1
            except Exception as e:
                failed_count += 1
                print(f"[Indexing] 处理分块失败 ({chunk.chunk_id}): {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # 标记所有相关事件为已索引
        if processed_event_ids:
            event_ids_list = list(processed_event_ids)
            self.db_client.mark_events_as_indexed(event_ids_list)
        
        return {'chunks': len(chunks), 'success': success_count, 'failed': failed_count}
    
    def _index_events(self, events: List[EventLog]) -> None:
        """对事件进行分块和嵌入（内部方法，供 process_video 调用）"""
        # 分块
        chunks = self.chunker.chunk_events(events)
        print(f"  生成 {len(chunks)} 个分块")
        
        # 为每个分块生成嵌入并写入数据库
        for i, chunk in enumerate(chunks, 1):
            try:
                # 生成嵌入
                embedding = self.embedding_service.embed_text(chunk.chunk_text)
                chunk.embedding = embedding
                
                # 写入数据库
                self.db_client.insert_log_chunk(
                    chunk_id=chunk.chunk_id,
                    chunk_text=chunk.chunk_text,
                    related_event_ids=chunk.related_event_ids,
                    embedding=embedding,
                    start_time=chunk.start_time.isoformat(),
                    end_time=chunk.end_time.isoformat()
                )
                
                if i % 5 == 0:
                    print(f"  已处理 {i}/{len(chunks)} 个分块")
            except Exception as e:
                print(f"  处理分块失败 ({chunk.chunk_id}): {e}")
                continue
    
    def close(self):
        """关闭资源"""
        if self.db_client:
            self.db_client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

