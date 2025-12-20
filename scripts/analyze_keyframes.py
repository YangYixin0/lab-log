#!/usr/bin/env python3
"""分析视频的关键帧位置和间隔"""

import sys
import subprocess
import json
from pathlib import Path


def get_keyframes(video_path: str):
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


def get_video_duration(video_path: str):
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


def analyze_keyframes(video_path: str):
    """分析视频的关键帧"""
    if not Path(video_path).exists():
        print(f"错误: 视频文件不存在: {video_path}")
        return
    
    print(f"\n{'='*70}")
    print(f"分析视频: {video_path}")
    print(f"{'='*70}")
    
    # 获取视频时长
    duration = get_video_duration(video_path)
    print(f"\n视频总时长: {duration:.2f} 秒 ({duration/60:.2f} 分钟)")
    
    # 获取关键帧
    keyframes = get_keyframes(video_path)
    
    if not keyframes:
        print("\n未找到关键帧")
        return
    
    print(f"\n关键帧总数: {len(keyframes)} 个")
    print(f"关键帧密度: {len(keyframes)/duration*60:.2f} 个/分钟")
    
    # 显示所有关键帧位置
    print(f"\n所有关键帧位置:")
    if len(keyframes) <= 20:
        for i, kf in enumerate(keyframes, 1):
            print(f"  {i:3d}. {kf:8.2f} 秒 ({kf/60:6.2f} 分钟)")
    else:
        print("  前10个:")
        for i, kf in enumerate(keyframes[:10], 1):
            print(f"  {i:3d}. {kf:8.2f} 秒 ({kf/60:6.2f} 分钟)")
        print("  ...")
        print("  后10个:")
        for i, kf in enumerate(keyframes[-10:], len(keyframes)-9):
            print(f"  {i:3d}. {kf:8.2f} 秒 ({kf/60:6.2f} 分钟)")
    
    # 计算关键帧间隔
    if len(keyframes) > 1:
        intervals = []
        for i in range(len(keyframes) - 1):
            interval = keyframes[i + 1] - keyframes[i]
            intervals.append(interval)
        
        print(f"\n关键帧间隔分析:")
        print(f"  间隔总数: {len(intervals)} 个")
        print(f"  平均间隔: {sum(intervals)/len(intervals):.2f} 秒 ({sum(intervals)/len(intervals)/60:.2f} 分钟)")
        print(f"  最小间隔: {min(intervals):.2f} 秒 ({min(intervals)/60:.2f} 分钟)")
        print(f"  最大间隔: {max(intervals):.2f} 秒 ({max(intervals)/60:.2f} 分钟)")
        
        # 显示间隔分布
        print(f"\n间隔分布:")
        if len(intervals) <= 20:
            for i, interval in enumerate(intervals, 1):
                print(f"  {i:3d}. {keyframes[i-1]:8.2f} -> {keyframes[i]:8.2f}: {interval:6.2f} 秒 ({interval/60:5.2f} 分钟)")
        else:
            print("  前10个间隔:")
            for i, interval in enumerate(intervals[:10], 1):
                print(f"  {i:3d}. {keyframes[i-1]:8.2f} -> {keyframes[i]:8.2f}: {interval:6.2f} 秒 ({interval/60:5.2f} 分钟)")
            print("  ...")
            print("  后10个间隔:")
            for i, interval in enumerate(intervals[-10:], len(intervals)-9):
                print(f"  {i:3d}. {keyframes[i-1]:8.2f} -> {keyframes[i]:8.2f}: {interval:6.2f} 秒 ({interval/60:5.2f} 分钟)")
        
        # 统计间隔范围
        short_intervals = [iv for iv in intervals if iv < 10]  # 小于10秒
        medium_intervals = [iv for iv in intervals if 10 <= iv < 60]  # 10-60秒
        long_intervals = [iv for iv in intervals if 60 <= iv < 300]  # 1-5分钟
        very_long_intervals = [iv for iv in intervals if iv >= 300]  # 超过5分钟
        
        print(f"\n间隔统计:")
        print(f"  < 10秒:     {len(short_intervals):3d} 个 ({len(short_intervals)/len(intervals)*100:5.1f}%)")
        print(f"  10-60秒:    {len(medium_intervals):3d} 个 ({len(medium_intervals)/len(intervals)*100:5.1f}%)")
        print(f"  1-5分钟:    {len(long_intervals):3d} 个 ({len(long_intervals)/len(intervals)*100:5.1f}%)")
        print(f"  >= 5分钟:   {len(very_long_intervals):3d} 个 ({len(very_long_intervals)/len(intervals)*100:5.1f}%)")
    
    # 检查第一个和最后一个关键帧
    print(f"\n关键帧位置:")
    print(f"  第一个关键帧: {keyframes[0]:.2f} 秒")
    if keyframes[0] > 0.1:
        print(f"    ⚠️ 第一个关键帧不在视频开始位置（偏移 {keyframes[0]:.2f} 秒）")
    else:
        print(f"    ✓ 第一个关键帧在视频开始位置")
    
    print(f"  最后一个关键帧: {keyframes[-1]:.2f} 秒")
    if abs(keyframes[-1] - duration) > 0.1:
        print(f"    ⚠️ 最后一个关键帧不在视频结束位置（距离结束 {duration - keyframes[-1]:.2f} 秒）")
    else:
        print(f"    ✓ 最后一个关键帧在视频结束位置")


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/analyze_keyframes.py <视频文件1> [视频文件2] ...")
        sys.exit(1)
    
    for video_path in sys.argv[1:]:
        analyze_keyframes(video_path)
    
    # 如果提供了多个视频，进行比较
    if len(sys.argv) > 2:
        print(f"\n{'='*70}")
        print("比较分析")
        print(f"{'='*70}")
        
        videos_info = []
        for video_path in sys.argv[1:]:
            duration = get_video_duration(video_path)
            keyframes = get_keyframes(video_path)
            videos_info.append({
                'path': video_path,
                'name': Path(video_path).name,
                'duration': duration,
                'keyframes': keyframes,
                'count': len(keyframes)
            })
        
        print(f"\n关键帧数量比较:")
        for info in videos_info:
            print(f"  {info['name']:40s}: {info['count']:3d} 个关键帧, 密度 {info['count']/info['duration']*60:.2f} 个/分钟")
        
        if len(videos_info) == 2:
            kf1 = videos_info[0]['keyframes']
            kf2 = videos_info[1]['keyframes']
            
            # 计算间隔
            intervals1 = [kf1[i+1] - kf1[i] for i in range(len(kf1)-1)] if len(kf1) > 1 else []
            intervals2 = [kf2[i+1] - kf2[i] for i in range(len(kf2)-1)] if len(kf2) > 1 else []
            
            if intervals1 and intervals2:
                avg1 = sum(intervals1) / len(intervals1)
                avg2 = sum(intervals2) / len(intervals2)
                print(f"\n平均间隔比较:")
                print(f"  {videos_info[0]['name']:40s}: {avg1:.2f} 秒")
                print(f"  {videos_info[1]['name']:40s}: {avg2:.2f} 秒")


if __name__ == '__main__':
    main()

