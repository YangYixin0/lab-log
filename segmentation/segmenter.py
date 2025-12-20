"""视频分段（GOP 对齐）"""

import subprocess
import json
import uuid
from pathlib import Path
from typing import List

from storage.models import VideoSegment


class VideoSegmenter:
    """视频分段器"""
    
    def __init__(self, target_duration: float = 60.0, use_temporary_files: bool = False):
        """
        初始化分段器
        
        Args:
            target_duration: 目标分段时长（秒），默认 60 秒
            use_temporary_files: 是否生成临时分段文件，False 时使用原始文件 + 时间范围
        """
        self.target_duration = target_duration
        self.use_temporary_files = use_temporary_files
    
    def segment(self, video_path: str) -> List[VideoSegment]:
        """
        将视频分段，GOP 对齐，目标时长约 60s
        
        Args:
            video_path: 视频文件路径
        
        Returns:
            分段列表
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        
        # 获取视频信息
        video_info = self._get_video_info(str(video_path))
        duration = float(video_info.get('duration', 0))
        
        if duration <= 0:
            raise ValueError(f"无法获取视频时长: {video_path}")
        
        segments = []
        current_time = 0.0
        segment_index = 0
        
        while current_time < duration:
            # 计算当前分段结束时间
            end_time = min(current_time + self.target_duration, duration)
            
            # 查找最近的 GOP 边界（I 帧）
            # 简化处理：使用 ffmpeg 的 keyframe 检测
            actual_end_time = self._find_nearest_keyframe(
                str(video_path), current_time, end_time
            )
            
            # 如果实际结束时间小于当前时间，至少前进 1 秒
            if actual_end_time <= current_time:
                actual_end_time = min(current_time + 1.0, duration)
            
            segment_id = f"{video_path.stem}_seg_{segment_index:04d}"
            
            if self.use_temporary_files:
                # 生成临时分段文件
                segment_path = self._extract_segment(
                    str(video_path), segment_id, current_time, actual_end_time
                )
            else:
                # 使用原始文件路径（调用者需要根据时间范围处理）
                segment_path = str(video_path)
            
            segment = VideoSegment(
                segment_id=segment_id,
                video_path=segment_path,
                start_time=current_time,
                end_time=actual_end_time
            )
            segments.append(segment)
            
            current_time = actual_end_time
            segment_index += 1
        
        return segments
    
    def _get_video_info(self, video_path: str) -> dict:
        """获取视频信息"""
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            video_path
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            info = json.loads(result.stdout)
            return info.get('format', {})
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffprobe 执行失败: {e}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"解析视频信息失败: {e}")
    
    def _find_nearest_keyframe(self, video_path: str, start_time: float,
                               target_end_time: float) -> float:
        """
        查找最近的 GOP 边界（关键帧）
        
        简化实现：在目标结束时间附近查找最近的 I 帧
        """
        # 使用 ffprobe 查找关键帧
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-select_streams', 'v:0',
            '-show_entries', 'frame=pkt_pts_time,key_frame',
            '-of', 'json',
            '-read_intervals', f'%+{start_time}#{target_end_time + 10}',  # 向后查找 10 秒
            video_path
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)
            
            frames = data.get('frames', [])
            # 找到目标时间之后最近的 I 帧
            for frame in frames:
                if frame.get('key_frame') == 1:
                    pts_time = float(frame.get('pkt_pts_time', 0))
                    if start_time < pts_time <= target_end_time + 10:
                        # 返回这个关键帧时间，但如果太远就返回目标时间
                        if pts_time <= target_end_time * 1.2:  # 允许 20% 误差
                            return pts_time
            
            # 如果没找到合适的 I 帧，返回目标时间
            return target_end_time
        except Exception:
            # 如果查找关键帧失败，返回目标时间
            return target_end_time
    
    def _extract_segment(self, video_path: str, segment_id: str,
                        start_time: float, end_time: float) -> str:
        """提取分段到临时文件"""
        output_dir = Path(video_path).parent / "segments"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{segment_id}.mp4"
        
        duration = end_time - start_time
        
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-ss', str(start_time),
            '-t', str(duration),
            '-c', 'copy',  # 直接拷贝，不重编码
            '-avoid_negative_ts', 'make_zero',
            '-y',  # 覆盖已存在文件
            str(output_path)
        ]
        
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                stderr=subprocess.PIPE
            )
            return str(output_path)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"提取分段失败: {e}\n"
                f"stderr: {e.stderr.decode('utf-8', errors='ignore')}"
            )

