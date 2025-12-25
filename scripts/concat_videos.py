#!/usr/bin/env python3
"""将录制会话目录中的视频片段重新编码并按顺序连接"""

import sys
import argparse
import subprocess
import math
from pathlib import Path
from typing import List, Tuple


def get_video_fps(video_path: Path) -> float:
    """
    使用 ffprobe 获取视频帧率
    
    Args:
        video_path: 视频文件路径
        
    Returns:
        帧率（fps），如果获取失败则返回 0
    """
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(video_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        fps_str = result.stdout.strip()
        
        # 解析分数格式（如 "30/1" 或 "353/12"）
        if '/' in fps_str:
            numerator, denominator = map(int, fps_str.split('/'))
            fps = numerator / denominator
        else:
            fps = float(fps_str)
        
        return fps
    except (subprocess.CalledProcessError, ValueError, ZeroDivisionError) as e:
        print(f"警告: 无法获取 {video_path} 的帧率: {e}")
        return 0.0


def find_max_fps(video_files: List[Path]) -> int:
    """
    找到所有视频中的最高帧率并向上取整
    
    Args:
        video_files: 视频文件路径列表
        
    Returns:
        最高帧率（向上取整后的整数）
    """
    max_fps = 0.0
    for video_file in video_files:
        fps = get_video_fps(video_file)
        if fps > max_fps:
            max_fps = fps
        print(f"  {video_file.name}: {fps:.2f} fps")
    
    # 向上取整
    target_fps = math.ceil(max_fps)
    print(f"\n最高帧率: {max_fps:.2f} fps，统一到: {target_fps} fps")
    return target_fps


def concat_videos(video_files: List[Path], output_path: Path, target_fps: int) -> bool:
    """
    重新编码并连接视频文件
    
    Args:
        video_files: 视频文件路径列表（已排序）
        output_path: 输出文件路径
        target_fps: 目标帧率
        
    Returns:
        是否成功
    """
    if not video_files:
        print("错误: 没有视频文件需要处理")
        return False
    
    print(f"\n开始连接 {len(video_files)} 个视频片段...")
    
    # 构建 ffmpeg 命令
    # 使用 concat filter 来统一帧率并连接
    filter_parts = []
    input_args = []
    
    for i, video_file in enumerate(video_files):
        input_args.extend(['-i', str(video_file)])
        # 为每个输入添加 fps filter 统一帧率
        filter_parts.append(f"[{i}:v]fps={target_fps}[v{i}]")
    
    # 连接所有视频
    concat_inputs = ''.join([f"[v{i}]" for i in range(len(video_files))])
    filter_parts.append(f"{concat_inputs}concat=n={len(video_files)}:v=1[outv]")
    
    filter_complex = ';'.join(filter_parts)
    
    cmd = [
        'ffmpeg',
        '-y',  # 覆盖输出文件
    ] + input_args + [
        '-filter_complex', filter_complex,
        '-map', '[outv]',
        '-c:v', 'libx264',  # 使用 H.264 编码
        '-preset', 'medium',  # 编码速度与质量平衡
        '-crf', '23',  # 质量参数（18-28，23 是默认值）
        '-pix_fmt', 'yuv420p',  # 兼容性最好的像素格式
        str(output_path)
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    print("这可能需要一些时间，请耐心等待...\n")
    
    try:
        # 实时显示进度
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # 显示输出（ffmpeg 的进度信息在 stderr，但我们已经合并到 stdout）
        for line in process.stdout:
            # 只显示关键信息，避免输出过多
            if 'frame=' in line or 'time=' in line or 'error' in line.lower():
                print(line.strip())
        
        process.wait()
        
        if process.returncode == 0:
            print(f"\n✓ 成功！输出文件: {output_path}")
            # 显示输出文件信息
            if output_path.exists():
                size_mb = output_path.stat().st_size / (1024 * 1024)
                print(f"  文件大小: {size_mb:.2f} MB")
            return True
        else:
            print(f"\n✗ 失败！ffmpeg 返回码: {process.returncode}")
            return False
            
    except Exception as e:
        print(f"\n✗ 执行失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="将录制会话目录中的视频片段重新编码并按顺序连接",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/concat_videos.py recordings/20251224_220952
  python scripts/concat_videos.py recordings/20251224_220952 -o output.mp4
        """
    )
    parser.add_argument(
        'session_dir',
        type=str,
        help='录制会话目录路径（包含 .mp4 视频文件）'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='输出文件路径（默认: <session_dir>/concatenated.mp4）'
    )
    
    args = parser.parse_args()
    
    session_dir = Path(args.session_dir)
    if not session_dir.exists():
        print(f"错误: 目录不存在: {session_dir}")
        sys.exit(1)
    
    if not session_dir.is_dir():
        print(f"错误: 不是目录: {session_dir}")
        sys.exit(1)
    
    # 查找所有 .mp4 文件并按文件名排序（文件名包含时间戳，排序后就是时间顺序）
    video_files = sorted(session_dir.glob("*.mp4"))
    
    if not video_files:
        print(f"错误: 目录中没有找到 .mp4 文件: {session_dir}")
        sys.exit(1)
    
    print(f"找到 {len(video_files)} 个视频文件:")
    for video_file in video_files:
        print(f"  - {video_file.name}")
    
    # 确定输出文件路径
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = session_dir / "concatenated.mp4"
    
    # 如果输出文件已存在，询问是否覆盖（但 -y 参数会自动覆盖）
    if output_path.exists():
        print(f"\n警告: 输出文件已存在，将被覆盖: {output_path}")
    
    # 检测所有视频的帧率
    print("\n检测视频帧率...")
    target_fps = find_max_fps(video_files)
    
    if target_fps <= 0:
        print("错误: 无法确定有效的帧率")
        sys.exit(1)
    
    # 连接视频
    success = concat_videos(video_files, output_path, target_fps)
    
    if success:
        print("\n完成！")
        sys.exit(0)
    else:
        print("\n失败！")
        sys.exit(1)


if __name__ == "__main__":
    main()

