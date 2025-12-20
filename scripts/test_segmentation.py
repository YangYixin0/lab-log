#!/usr/bin/env python3
"""测试分段逻辑，不调用大模型"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from segmentation.segmenter import VideoSegmenter


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/test_segmentation.py <视频文件路径>")
        sys.exit(1)
    
    video_path = sys.argv[1]
    
    print(f"测试分段: {video_path}")
    print("=" * 60)
    
    # 创建分段器
    segmenter = VideoSegmenter(use_temporary_files=True)
    
    # 执行分段
    segments = segmenter.segment(video_path)
    
    print(f"\n分段完成，共 {len(segments)} 个分段\n")
    
    # 显示每个分段的信息
    for i, segment in enumerate(segments, 1):
        print(f"分段 {i}: {segment.segment_id}")
        print(f"  起始时间: {segment.start_time:.2f} 秒")
        print(f"  结束时间: {segment.end_time:.2f} 秒")
        print(f"  时长: {segment.end_time - segment.start_time:.2f} 秒 ({(segment.end_time - segment.start_time)/60:.2f} 分钟)")
        
        # 检查分段文件
        if Path(segment.video_path).exists():
            import subprocess
            try:
                cmd = [
                    'ffprobe',
                    '-v', 'quiet',
                    '-show_entries', 'format=duration',
                    '-of', 'json',
                    segment.video_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                import json
                data = json.loads(result.stdout)
                format_info = data.get('format', {})
                file_duration = float(format_info.get('duration', 0))
                print(f"  文件时长: {file_duration:.2f} 秒")
                # 验证：segment.start_time + file_duration 应该等于 segment.end_time
                calculated_end = segment.start_time + file_duration
                if abs(calculated_end - segment.end_time) > 1.0:
                    print(f"  ⚠️ 注意: 计算出的结束时间 ({calculated_end:.2f} 秒) 与记录的结束时间 ({segment.end_time:.2f} 秒) 不一致")
            except Exception as e:
                print(f"  无法获取文件信息: {e}")
        print()
    
    # 检查分段是否连续
    print("=" * 60)
    print("分段连续性检查:")
    print("=" * 60)
    for i in range(len(segments) - 1):
        current_end = segments[i].end_time
        next_start = segments[i + 1].start_time
        gap = next_start - current_end
        
        if abs(gap) < 1.0:  # 允许1秒的误差
            print(f"分段 {i+1} 到 {i+2}: 连续 (间隔: {gap:.2f} 秒)")
        elif gap < 0:
            print(f"分段 {i+1} 到 {i+2}: ⚠️ 重叠 {abs(gap):.2f} 秒")
        else:
            print(f"分段 {i+1} 到 {i+2}: ⚠️ 有间隔 {gap:.2f} 秒")
    
    print("\n测试完成！")


if __name__ == '__main__':
    main()

