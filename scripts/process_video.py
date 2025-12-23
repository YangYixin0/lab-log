#!/usr/bin/env python3
"""视频处理入口脚本"""

import sys
import argparse
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from orchestration.pipeline import VideoLogPipeline


def main():
    parser = argparse.ArgumentParser(description='处理视频并生成日志')
    parser.add_argument('video_path', type=str, help='视频文件路径')
    
    args = parser.parse_args()
    
    video_path = Path(args.video_path)
    if not video_path.exists():
        print(f"错误: 视频文件不存在: {video_path}")
        sys.exit(1)
    
    # 索引不再由视频处理触发，统一由独立脚本处理
    with VideoLogPipeline(enable_indexing=False) as pipeline:
        try:
            events = pipeline.process_video(str(video_path))
            print(f"\n处理完成！共生成 {len(events)} 个事件日志")
        except Exception as e:
            print(f"处理失败: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == '__main__':
    main()

