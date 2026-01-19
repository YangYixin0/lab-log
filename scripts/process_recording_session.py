#!/usr/bin/env python3
"""处理一次采集会话的所有分段（包含二维码结果）并传递给视频理解（使用动态上下文）"""

import sys
import argparse
import json
import os
import time
from pathlib import Path
from typing import List

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from storage.models import VideoSegment
from storage.seekdb_client import SeekDBClient
from utils.segment_time_parser import parse_segment_times, extract_date_from_segment_id

# 动态上下文相关模块
from context.appearance_cache import AppearanceCache
from context.event_context import EventContext
from video_processing.qwen3_vl_processor import Qwen3VLProcessor
from log_writer.writer import SimpleLogWriter

# 加载环境变量
load_dotenv()

# 环境变量配置
def get_config(key: str, default, type_func: type = str):
    """从环境变量读取配置"""
    value = os.getenv(key)
    if value is None:
        return default
    if type_func == bool:
        return value.lower() in ('true', '1', 'yes', 'on')
    return type_func(value)

DYNAMIC_CONTEXT_ENABLED = get_config('DYNAMIC_CONTEXT_ENABLED', True, bool)
MAX_RECENT_EVENTS = get_config('MAX_RECENT_EVENTS', 20, int)
APPEARANCE_DUMP_INTERVAL = get_config('APPEARANCE_DUMP_INTERVAL', 5, int)  # 每 N 个分段 dump 一次

# 调试日志目录
DEBUG_LOG_DIR = Path("logs_debug")
DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_segments(session_dir: Path, target_duration: float) -> List[VideoSegment]:
    """读取目录下的 mp4 分段及对应二维码结果"""
    mp4_files = sorted(session_dir.glob("*.mp4"))
    segments: List[VideoSegment] = []
    for mp4_file in mp4_files:
        segment_id = mp4_file.stem
        qr_file = mp4_file.with_name(f"{segment_id}_qr.json")
        qr_results = []
        if qr_file.exists():
            try:
                qr_results = json.loads(qr_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[Warn] 读取二维码结果失败 {qr_file}: {e}")
                qr_results = []
        start_time, end_time = parse_segment_times(segment_id, target_duration)
        segments.append(
            VideoSegment(
                segment_id=segment_id,
                video_path=str(mp4_file),
                start_time=start_time,
                end_time=end_time,
                qr_results=qr_results,
            )
        )
    return segments


def main():
    parser = argparse.ArgumentParser(description="处理一次采集会话的分段（含二维码结果）")
    parser.add_argument("session_dir", type=str, help="会话目录（包含 mp4 和 _qr.json）")
    parser.add_argument(
        "--target-duration",
        type=float,
        default=60.0,
        help="分段目标时长，解析时间戳失败时使用（秒），默认60",
    )

    args = parser.parse_args()
    session_path = Path(args.session_dir)
    if not session_path.exists():
        print(f"错误: 会话目录不存在: {session_path}")
        sys.exit(1)

    # 从会话目录提取名义日期 (格式: YYYYMMDD_HHMMSS)
    session_name = session_path.name
    try:
        # 提取前8位 YYYYMMDD
        date_part = session_name.split('_')[0]
        if len(date_part) != 8 or not date_part.isdigit():
            raise ValueError(f"目录名日期部分无效: {date_part}")
        nominal_date = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}"
        print(f"[Context]: 提取到名义日期: {nominal_date}")
    except Exception as e:
        print(f"错误: 无法从目录名 {session_name} 提取日期。格式应为 YYYYMMDD_HHMMSS。详细错误: {e}")
        sys.exit(1)

    # 询问是否清空测试数据
    clear_confirm = input("是否在处理前清空现有测试数据 (appearances.json, event_logs.jsonl 等)? (y/N): ")
    if clear_confirm.lower() == 'y':
        print("[System]: 正在执行 scripts/clear_test_data.py...")
        import subprocess
        try:
            subprocess.run([sys.executable, str(project_root / "scripts" / "clear_test_data.py")], check=True)
            print("[System]: 测试数据已清空")
        except Exception as e:
            print(f"[Error]: 清空测试数据失败: {e}")
            sys.exit(1)

    segments = load_segments(session_path, args.target_duration)
    if not segments:
        print(f"错误: 目录中未找到 mp4 分段: {session_path}")
        sys.exit(1)

    # 初始化动态上下文组件
    appearance_cache = None
    event_context = None
    db_client = None
    log_writer = None
    video_processor = None
    
    try:
        if DYNAMIC_CONTEXT_ENABLED:
            print("[Context]: 初始化动态上下文...")
            
            # 创建数据库客户端
            db_client = SeekDBClient()
            
            # 创建人物外貌缓存（尝试从文件加载）
            appearance_cache = AppearanceCache()
            appearance_cache.nominal_date = nominal_date
            appearance_cache_path = DEBUG_LOG_DIR / "appearances.json"
            if appearance_cache_path.exists():
                loaded = appearance_cache.load_from_file(str(appearance_cache_path))
                if loaded:
                    print(f"[Context]: 加载外貌缓存成功，共 {appearance_cache.get_record_count()} 条记录")
            
            # 创建事件上下文（从 JSONL 文件读取）
            event_context = EventContext()
            
            # 创建日志写入器（不加密）
            log_writer = SimpleLogWriter(db_client)
            
            # 创建视频处理器（使用动态上下文）
            video_processor = Qwen3VLProcessor(
                appearance_cache=appearance_cache,
                event_context=event_context,
                max_recent_events=MAX_RECENT_EVENTS
            )
            
            print(f"[Context]: 动态上下文初始化成功")
        else:
            print("[Warning]: DYNAMIC_CONTEXT_ENABLED=false，将使用传统模式")
            from orchestration.pipeline import VideoLogPipeline
            # 注意：传统模式使用 context manager，但这里我们手动管理
            # 为了简化，我们创建一个临时的 pipeline 实例
            pipeline = VideoLogPipeline(enable_indexing=False)
            video_processor = pipeline.video_processor
            log_writer = pipeline.log_writer
            # 注意：传统模式下，pipeline 会在 finally 块中自动清理（如果实现了 __enter__/__exit__）
        
        all_events = []
        total_written = 0
        processed_count = 0
        print(f"开始处理会话目录: {session_path}，共 {len(segments)} 个分段")
        
        for i, segment in enumerate(segments, 1):
            print(f"  处理分段 {i}/{len(segments)}: {segment.segment_id}")
            try:
                if DYNAMIC_CONTEXT_ENABLED and video_processor:
                    # 从 segment_id 提取视频日期
                    segment_date = extract_date_from_segment_id(segment.segment_id)
                    
                    # 获取最近事件和最大事件编号（使用视频日期而非今天）
                    recent_events = []
                    max_event_id = 0
                    if event_context:
                        if segment_date:
                            recent_events = event_context.get_recent_events(MAX_RECENT_EVENTS, date=segment_date)
                            max_event_id = event_context.get_max_event_id_number(date=segment_date)
                        else:
                            # 如果无法解析日期，回退到使用今天
                            recent_events = event_context.get_recent_events(MAX_RECENT_EVENTS)
                            max_event_id = event_context.get_max_event_id_number()
                    
                    # 使用动态上下文处理
                    result = video_processor.process_segment_with_context(
                        segment,
                        appearance_cache,
                        recent_events,
                        max_event_id
                    )
                    
                    # 应用外貌更新
                    video_processor._apply_appearance_updates(result.appearance_updates)
                    
                    appearance_update_count = len(result.appearance_updates)
                    events = result.events
                else:
                    # 传统模式
                    result = video_processor.process_segment(segment)
                    events = result.events
                    appearance_update_count = 0
                
                print(f"    识别到 {len(events)} 个事件", end="")
                if appearance_update_count > 0:
                    print(f"，外貌更新={appearance_update_count}", end="")
                print()
                
                # 写入事件
                for event in events:
                    try:
                        log_writer.write_event_log(event)
                        total_written += 1
                    except Exception as e:
                        print(f"    写入事件失败 ({event.event_id}): {e}")
                        continue
                
                all_events.extend(events)
                processed_count += 1
                print(f"    已写入 {len(events)} 个事件")
                
                # 周期性保存外貌缓存
                if DYNAMIC_CONTEXT_ENABLED and appearance_cache and processed_count % APPEARANCE_DUMP_INTERVAL == 0:
                    appearance_cache_path = DEBUG_LOG_DIR / "appearances.json"
                    try:
                        appearance_cache.dump_to_file(str(appearance_cache_path))
                        print(f"[Context]: 外貌缓存已保存，共 {appearance_cache.get_record_count()} 条记录")
                    except Exception as e:
                        print(f"[Context]: 保存外貌缓存失败: {e}")
                
            except Exception as e:
                print(f"    处理分段失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # 最终保存外貌缓存
        if DYNAMIC_CONTEXT_ENABLED and appearance_cache:
            appearance_cache_path = DEBUG_LOG_DIR / "appearances.json"
            try:
                appearance_cache.dump_to_file(str(appearance_cache_path))
                print(f"[Context]: 最终保存外貌缓存，共 {appearance_cache.get_record_count()} 条记录")
            except Exception as e:
                print(f"[Context]: 保存外貌缓存失败: {e}")
        
        print(f"\n处理完成！共识别 {len(all_events)} 个事件，已写入 {total_written} 个事件")
        
    finally:
        # 清理资源
        if event_context:
            event_context.close()
        if db_client:
            db_client.close()


if __name__ == "__main__":
    main()

