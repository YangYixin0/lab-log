#!/usr/bin/env python3
"""处理一次采集会话的所有分段（包含二维码结果）并传递给视频理解"""

import sys
import argparse
import json
import time
from pathlib import Path
from typing import List

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from orchestration.pipeline import VideoLogPipeline
from storage.models import VideoSegment
from utils.segment_time_parser import parse_segment_times


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

    segments = load_segments(session_path, args.target_duration)
    if not segments:
        print(f"错误: 目录中未找到 mp4 分段: {session_path}")
        sys.exit(1)

    # 索引不再由视频处理触发，统一由独立脚本处理
    with VideoLogPipeline(enable_indexing=False) as pipeline:
        all_events = []
        total_written = 0
        print(f"开始处理会话目录: {session_path}，共 {len(segments)} 个分段")
        for i, segment in enumerate(segments, 1):
            print(f"  处理分段 {i}/{len(segments)}: {segment.segment_id}")
            try:
                result = pipeline.video_processor.process_segment(segment)
                print(f"    识别到 {len(result.events)} 个事件")
                for event in result.events:
                    try:
                        pipeline.log_writer.write_event_log(event)
                        total_written += 1
                    except Exception as e:
                        print(f"    写入事件失败 ({event.event_id}): {e}")
                        continue
                all_events.extend(result.events)
                print(f"    已写入 {len(result.events)} 个事件")
            except Exception as e:
                print(f"    处理分段失败: {e}")
                import traceback
                traceback.print_exc()
                continue

        print(f"\n处理完成！共识别 {len(all_events)} 个事件，已写入 {total_written} 个事件")


if __name__ == "__main__":
    main()

