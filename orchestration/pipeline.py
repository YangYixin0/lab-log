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
            enable_indexing: 是否启用索引（分块和嵌入），默认 False（索引通常在测试时手动触发或生产环境定时任务中执行）
        """
        self.db_client = db_client or SeekDBClient()
        
        self.video_processor = video_processor or Qwen3VLProcessor()
        self.log_writer = log_writer or LogWriter(self.db_client)
        self.chunker = chunker or LogChunker()
        self.embedding_service = embedding_service or EmbeddingService()
        self.enable_indexing = enable_indexing
    
    def process_video(self, video_path: str) -> List[EventLog]:
        """
        处理视频：分段 → 理解 → 写入 → 嵌入
        
        Args:
            video_path: 视频文件路径
        
        Returns:
            所有生成的事件日志列表
        """
        print(f"开始处理视频: {video_path}")
        
        # 1. 视频分段
        print("步骤 1/4: 视频分段...")
        segmenter = VideoSegmenter()
        segments = segmenter.segment(video_path)
        print(f"  分段完成，共 {len(segments)} 个分段")
        
        # 2. 视频理解
        print("步骤 2/4: 视频理解...")
        all_events = []
        for i, segment in enumerate(segments, 1):
            print(f"  处理分段 {i}/{len(segments)}: {segment.segment_id}")
            try:
                result = self.video_processor.process_segment(segment)
                print(f"    识别到 {len(result.events)} 个事件")
                all_events.extend(result.events)
            except Exception as e:
                print(f"    处理分段失败: {e}")
                continue
        
        print(f"  视频理解完成，共识别 {len(all_events)} 个事件")
        
        # 3. 写入日志
        from config.encryption_config import EncryptionConfig
        encryption_status = "（加密）" if EncryptionConfig.should_encrypt() else ""
        print(f"步骤 3/4: 写入日志{encryption_status}...")
        for i, event in enumerate(all_events, 1):
            try:
                self.log_writer.write_event_log(event)
                if i % 10 == 0:
                    print(f"  已写入 {i}/{len(all_events)} 个事件")
            except Exception as e:
                print(f"  写入事件失败 ({event.event_id}): {e}")
                continue
        
        print(f"  日志写入完成，共写入 {len(all_events)} 个事件")
        
        # 4. 分块与嵌入（可选）
        if self.enable_indexing and all_events:
            print("步骤 4/4: 分块与嵌入...")
            try:
                self._index_events(all_events)
                print("  索引完成")
            except Exception as e:
                print(f"  索引失败: {e}")
        else:
            print("步骤 4/4: 跳过索引（已禁用或无事件）")
        
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
            return {'chunks': 0, 'success': 0, 'failed': 0}
        
        # 为每个分块生成嵌入并写入数据库
        success_count = 0
        failed_count = 0
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
                success_count += 1
            except Exception as e:
                failed_count += 1
                print(f"[Indexing] 处理分块失败 ({chunk.chunk_id}): {e}")
                import traceback
                traceback.print_exc()
                continue
        
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

