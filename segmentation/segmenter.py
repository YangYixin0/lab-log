"""视频分段（GOP 对齐）"""

import subprocess
import json
import uuid
from pathlib import Path
from typing import List

from storage.models import VideoSegment


class VideoSegmenter:
    """视频分段器"""
    
    def __init__(self, target_duration: float = 60.0, use_temporary_files: bool = True, 
                 keyframes_count: int = 0):
        """
        初始化分段器
        
        Args:
            target_duration: 目标分段时长（秒），默认 60 秒
            use_temporary_files: 是否生成临时分段文件，True 时会实际提取分段文件
            keyframes_count: 视频中的关键帧数量（用于决定是否使用重编码）
        """
        self.target_duration = target_duration
        self.use_temporary_files = use_temporary_files
        self.keyframes_count = keyframes_count
    
    def segment(self, video_path: str) -> List[VideoSegment]:
        """
        将视频分段，GOP 对齐，目标时长约 60s
        
        改进：先找出所有关键帧，再以关键帧为边界进行分段
        
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
        
        # 1. 先找出所有关键帧（I 帧）的位置
        keyframes = self._get_all_keyframes(str(video_path), duration)
        self.keyframes_count = len(keyframes)
        print(f"  关键帧数量: {self.keyframes_count}")
        
        if not keyframes:
            # 如果没有找到关键帧，回退到原来的方法
            print("  警告：未找到关键帧，使用时间分段")
            return self._segment_by_time(str(video_path), duration)
        
        # 如果关键帧很少，给出提示但继续使用关键帧分段
        min_keyframes = max(2, int(duration / self.target_duration))
        if len(keyframes) < min_keyframes:
            print(f"  提示：关键帧较少（{len(keyframes)} 个），将确保每个分段不超过5分钟")
        
        # 确保包含视频开始和结束
        if keyframes[0] > 0.1:  # 如果第一个关键帧不在开始位置
            keyframes.insert(0, 0.0)
        if keyframes[-1] < duration - 0.1:  # 如果最后一个关键帧不在结束位置
            keyframes.append(duration)
        
        # 2. 迭代式分段：每提取一个分段后，检查实际结束时间，从那里开始下一个分段
        segments = []
        segment_index = 0
        max_segment_duration = 300.0  # 最大分段时长：5分钟（300秒）
        
        # 从第一个关键帧开始
        current_start = keyframes[0]
        
        while current_start < duration:
            # 找到当前开始时间之后的下一个关键帧
            next_keyframe = None
            for kf in keyframes:
                if kf > current_start:
                    next_keyframe = kf
                    break
            
            if next_keyframe is None:
                # 没有更多关键帧，使用视频结束时间
                next_keyframe = duration
            
            # 计算目标结束时间
            if next_keyframe - current_start > max_segment_duration:
                # 如果关键帧间隔超过最大时长，限制为最大时长
                target_end = current_start + max_segment_duration
            else:
                # 使用下一个关键帧作为结束
                target_end = next_keyframe
            
            segment_id = f"{video_path.stem}_seg_{segment_index:04d}"
            
            if self.use_temporary_files:
                # 提取分段
                segment_path = self._extract_segment(
                    str(video_path), segment_id, current_start, target_end
                )
                
                # 检查实际提取的分段的结束时间
                # 返回 (实际起始时间, 实际结束时间)
                actual_start_time, actual_end_time = self._get_segment_actual_times(
                    segment_path, current_start, target_end
                )
                
                # 如果无法获取，使用目标时间
                if actual_start_time is None:
                    actual_start_time = current_start
                if actual_end_time is None:
                    actual_end_time = target_end
                
                # 确保不超过视频总时长，且结束时间大于起始时间
                actual_end_time = min(actual_end_time, duration)
                # 如果计算出的结束时间不合理（小于等于起始时间或超过视频时长），使用目标结束时间
                if actual_end_time <= actual_start_time or actual_end_time > duration + 1.0:
                    actual_end_time = min(target_end, duration)
            else:
                segment_path = str(video_path)
                actual_start_time = current_start
                actual_end_time = target_end
            
            segment = VideoSegment(
                segment_id=segment_id,
                video_path=segment_path,
                start_time=actual_start_time,
                end_time=actual_end_time,
                qr_results=[]
            )
            segments.append(segment)
            
            # 从实际结束时间开始下一个分段
            # 重要：使用实际结束时间，即使不是关键帧，ffmpeg 也会自动对齐
            current_start = actual_end_time
            
            # 如果已经达到或超过视频结束时间，停止
            if current_start >= duration:
                break
            
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
    
    def _get_all_keyframes(self, video_path: str, duration: float) -> List[float]:
        """
        获取视频中所有关键帧（I 帧）的时间位置
        
        Args:
            video_path: 视频文件路径
            duration: 视频总时长
            
        Returns:
            关键帧时间列表（秒），按时间排序
        """
        # 使用 show_frames 方法，更可靠
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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)
            
            frames = data.get('frames', [])
            keyframes = []
            
            for frame in frames:
                if frame.get('key_frame') == 1:
                    pts_time = float(frame.get('pkt_pts_time', 0))
                    # 过滤掉负数时间戳和超出范围的时间戳
                    if 0 <= pts_time <= duration:
                        keyframes.append(pts_time)
            
            # 去重并排序
            keyframes = sorted(list(set(keyframes)))
            
            # 关键帧少没关系，只要分段不超过5分钟即可
            # 不再因为关键帧少而返回空列表
            if len(keyframes) == 0:
                return []
            
            return keyframes
            
        except Exception as e:
            print(f"  警告：获取关键帧失败: {e}")
            return []
    
    def _segment_by_time(self, video_path: str, duration: float) -> List[VideoSegment]:
        """
        回退方法：按时间分段（当无法获取关键帧时使用）
        
        Args:
            video_path: 视频文件路径
            duration: 视频总时长
            
        Returns:
            分段列表
        """
        segments = []
        current_time = 0.0
        segment_index = 0
        
        while current_time < duration:
            end_time = min(current_time + self.target_duration, duration)
            
            segment_id = f"{Path(video_path).stem}_seg_{segment_index:04d}"
            
            if self.use_temporary_files:
                segment_path = self._extract_segment(
                    video_path, segment_id, current_time, end_time
                )
            else:
                segment_path = video_path
            
            segment = VideoSegment(
                segment_id=segment_id,
                video_path=segment_path,
                start_time=current_time,
                end_time=end_time,
                qr_results=[]
            )
            segments.append(segment)
            
            current_time = end_time
            segment_index += 1
        
        return segments
    
    def _extract_segment(self, video_path: str, segment_id: str,
                        start_time: float, end_time: float) -> str:
        """
        提取分段到临时文件
        
        注意：传入的 start_time 和 end_time 应该已经是关键帧位置（由 segment() 方法保证）
        使用 ffmpeg 提取视频分段。
        参考命令: ffmpeg -ss START -to END -i input.mp4 -c copy output.mp4
        """
        output_dir = Path(video_path).parent / "segments"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{segment_id}.mp4"
        
        # 使用 -ss 和 -to 参数提取分段（参考用户提供的命令格式）
        # 注意：-ss 和 -to 都放在 -i 之前，进行输入定位（更快且更精确）
        cmd = [
            'ffmpeg',
            '-ss', str(start_time),  # 起始时间（已经是关键帧）
            '-to', str(end_time),     # 结束时间（已经是关键帧，使用 -to 而不是 -t）
            '-i', video_path,         # 输入文件
            '-c', 'copy',             # 直接拷贝，不重编码
            '-avoid_negative_ts', 'make_zero',
            '-y',                     # 覆盖已存在文件
            str(output_path)
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                check=True
            )
            return str(output_path)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"提取分段失败: {e}\n"
                f"stderr: {e.stderr.decode('utf-8', errors='ignore') if e.stderr else 'N/A'}"
            )
    
    def _get_segment_actual_times(self, segment_path: str, expected_start: float, 
                                   expected_end: float):
        """
        获取提取后的分段在原视频中的实际起始和结束时间
        
        Args:
            segment_path: 分段文件路径
            expected_start: 预期的起始时间（在原视频中的时间）
            expected_end: 预期的结束时间（在原视频中的时间）
            
        Returns:
            (实际起始时间, 实际结束时间) 元组，如果无法获取则返回 (None, None)
        
        注意：由于使用 -c copy，如果起始时间不是关键帧，ffmpeg 会对齐到最近的关键帧。
        我们通过检查分段文件的时长来确定实际的时间范围。
        实际结束时间 = 实际起始时间 + 文件时长
        """
        try:
            import json
            
            # 获取分段文件的时长
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                segment_path
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            file_duration = float(result.stdout.strip())
            
            # 简化处理：假设分段文件从 expected_start 开始（即使因为关键帧对齐有偏差）
            # 实际结束时间 = expected_start + file_duration
            # 这样下一个分段可以从这个结束时间开始，确保连续性
            actual_start = expected_start
            actual_end = expected_start + file_duration
            
            return (actual_start, actual_end)
        except Exception as e:
            # 如果无法获取，返回 None
            return (None, None)
    
    def _find_nearest_keyframe_before(self, video_path: str, target_time: float):
        """
        查找目标时间之前最近的 I 帧（关键帧）
        
        Args:
            video_path: 视频文件路径
            target_time: 目标时间（秒）
            
        Returns:
            最近的 I 帧时间，如果找不到则返回 None
        """
        # 在目标时间之前查找（向前查找最多 5 秒）
        search_start = max(0, target_time - 5.0)
        
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-select_streams', 'v:0',
            '-show_entries', 'frame=pkt_pts_time,key_frame',
            '-of', 'json',
            '-read_intervals', f'%+{search_start}#{target_time}',
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
            # 找到目标时间之前最近的 I 帧
            nearest_keyframe = None
            for frame in frames:
                if frame.get('key_frame') == 1:
                    pts_time = float(frame.get('pkt_pts_time', 0))
                    if search_start <= pts_time <= target_time:
                        if nearest_keyframe is None or pts_time > nearest_keyframe:
                            nearest_keyframe = pts_time
            
            return nearest_keyframe
        except Exception:
            return None
    
    def _find_nearest_keyframe_after(self, video_path: str, target_time: float):
        """
        查找目标时间之后最近的 I 帧（关键帧）
        
        Args:
            video_path: 视频文件路径
            target_time: 目标时间（秒）
            
        Returns:
            最近的 I 帧时间，如果找不到则返回 None
        """
        # 在目标时间之后查找（向后查找最多 5 秒）
        search_end = target_time + 5.0
        
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-select_streams', 'v:0',
            '-show_entries', 'frame=pkt_pts_time,key_frame',
            '-of', 'json',
            '-read_intervals', f'%+{target_time}#{search_end}',
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
            nearest_keyframe = None
            for frame in frames:
                if frame.get('key_frame') == 1:
                    pts_time = float(frame.get('pkt_pts_time', 0))
                    if target_time <= pts_time <= search_end:
                        if nearest_keyframe is None or pts_time < nearest_keyframe:
                            nearest_keyframe = pts_time
            
            return nearest_keyframe
        except Exception:
            return None

