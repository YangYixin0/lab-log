#!/usr/bin/env python3
"""从视频中提取片段，自动对齐到关键帧"""

import sys
import subprocess
import json
from pathlib import Path


def parse_time(time_str: str) -> float:
    """解析时间字符串，支持 HH:MM:SS 或秒数"""
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 3:
            hours, minutes, seconds = map(float, parts)
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:
            minutes, seconds = map(float, parts)
            return minutes * 60 + seconds
    else:
        return float(time_str)


def format_time(seconds: float) -> str:
    """格式化时间为 HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"


def get_keyframes(video_path: str) -> list:
    """获取视频的所有关键帧位置"""
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-select_streams', 'v:0',
        '-show_frames',
        '-show_entries', 'frame=pkt_pts_time,key_frame',
        '-of', 'json',
        video_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        frames = data.get('frames', [])
        
        keyframes = []
        for frame in frames:
            if frame.get('key_frame') == 1:
                pts_time = float(frame.get('pkt_pts_time', 0))
                keyframes.append(pts_time)
        
        return sorted(set(keyframes))
    except Exception as e:
        print(f"错误: 无法获取关键帧: {e}")
        return []


def find_nearest_keyframe_before(keyframes: list, target_time: float) -> float:
    """找到目标时间之前最近的关键帧"""
    for kf in reversed(keyframes):
        if kf <= target_time:
            return kf
    # 如果没有找到，返回第一个关键帧
    return keyframes[0] if keyframes else 0.0


def find_nearest_keyframe_after(keyframes: list, target_time: float) -> float:
    """找到目标时间之后最近的关键帧"""
    for kf in keyframes:
        if kf >= target_time:
            return kf
    # 如果没有找到，返回最后一个关键帧
    return keyframes[-1] if keyframes else target_time


def get_video_duration(video_path: str) -> float:
    """获取视频总时长"""
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"错误: 无法获取视频时长: {e}")
        return 0.0


def extract_segment(video_path: str, start_time: float, end_time: float, 
                   output_path: str, align_to_keyframes: bool = True):
    """提取视频片段，可选择对齐到关键帧"""
    
    if not Path(video_path).exists():
        print(f"错误: 视频文件不存在: {video_path}")
        return False
    
    video_duration = get_video_duration(video_path)
    
    if start_time < 0:
        start_time = 0.0
    if end_time > video_duration:
        end_time = video_duration
    
    actual_start = start_time
    actual_end = end_time
    
    if align_to_keyframes:
        print(f"正在查找关键帧...")
        keyframes = get_keyframes(video_path)
        
        if not keyframes:
            print("警告: 未找到关键帧，使用原始时间")
        else:
            # 找到起始时间之前最近的关键帧
            aligned_start = find_nearest_keyframe_before(keyframes, start_time)
            # 找到结束时间之后最近的关键帧
            aligned_end = find_nearest_keyframe_after(keyframes, end_time)
            
            # 确保不超过视频总时长
            aligned_end = min(aligned_end, video_duration)
            
            print(f"\n时间对齐:")
            print(f"  原始起始时间: {format_time(start_time)} ({start_time:.2f} 秒)")
            print(f"  对齐后起始:   {format_time(aligned_start)} ({aligned_start:.2f} 秒)")
            if aligned_start < start_time:
                print(f"    ⚠️ 提前了 {start_time - aligned_start:.2f} 秒")
            elif aligned_start > start_time:
                print(f"    ⚠️ 延后了 {aligned_start - start_time:.2f} 秒")
            else:
                print(f"    ✓ 已经是关键帧位置")
            
            print(f"  原始结束时间: {format_time(end_time)} ({end_time:.2f} 秒)")
            print(f"  对齐后结束:   {format_time(aligned_end)} ({aligned_end:.2f} 秒)")
            if aligned_end > end_time:
                print(f"    ⚠️ 延长了 {aligned_end - end_time:.2f} 秒")
            elif aligned_end < end_time:
                print(f"    ⚠️ 缩短了 {end_time - aligned_end:.2f} 秒")
            else:
                print(f"    ✓ 已经是关键帧位置")
            
            actual_start = aligned_start
            actual_end = aligned_end
    
    # 构建 ffmpeg 命令
    # 使用 -ss 和 -to 在 -i 之前，进行输入定位
    cmd = [
        'ffmpeg',
        '-ss', str(actual_start),
        '-to', str(actual_end),
        '-i', video_path,
        '-c', 'copy',
        '-avoid_negative_ts', 'make_zero',
        '-y',
        output_path
    ]
    
    print(f"\n执行命令:")
    print(f"  {' '.join(cmd)}")
    print(f"\n正在提取片段...")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # 检查输出文件
        if Path(output_path).exists():
            output_duration = get_video_duration(output_path)
            print(f"\n✓ 提取成功!")
            print(f"  输出文件: {output_path}")
            print(f"  输出时长: {format_time(output_duration)} ({output_duration:.2f} 秒)")
            return True
        else:
            print(f"\n✗ 提取失败: 输出文件不存在")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"\n✗ 提取失败:")
        print(f"  stderr: {e.stderr}")
        return False


def main():
    if len(sys.argv) < 5:
        print("用法:")
        print("  python scripts/extract_segment_aligned.py <视频文件> <起始时间> <结束时间> <输出文件> [--no-align]")
        print("")
        print("时间格式:")
        print("  HH:MM:SS (例如: 00:30:48)")
        print("  MM:SS (例如: 30:48)")
        print("  秒数 (例如: 1848)")
        print("")
        print("示例:")
        print("  python scripts/extract_segment_aligned.py input.mp4 00:30:48 00:34:48 output.mp4")
        print("  python scripts/extract_segment_aligned.py input.mp4 1848 2088 output.mp4")
        print("")
        print("选项:")
        print("  --no-align  不对齐到关键帧，使用精确时间（可能无法使用 -c copy）")
        sys.exit(1)
    
    video_path = sys.argv[1]
    start_time_str = sys.argv[2]
    end_time_str = sys.argv[3]
    output_path = sys.argv[4]
    align_to_keyframes = '--no-align' not in sys.argv
    
    # 解析时间
    start_time = parse_time(start_time_str)
    end_time = parse_time(end_time_str)
    
    if start_time >= end_time:
        print(f"错误: 起始时间 ({start_time:.2f} 秒) 必须小于结束时间 ({end_time:.2f} 秒)")
        sys.exit(1)
    
    print(f"提取视频片段")
    print(f"{'='*70}")
    print(f"输入文件: {video_path}")
    print(f"输出文件: {output_path}")
    print(f"对齐到关键帧: {'是' if align_to_keyframes else '否'}")
    
    success = extract_segment(video_path, start_time, end_time, output_path, align_to_keyframes)
    
    if success:
        print(f"\n{'='*70}")
        print("完成!")
    else:
        print(f"\n{'='*70}")
        print("失败!")
        sys.exit(1)


if __name__ == '__main__':
    main()

