"""视频处理接口定义"""

from abc import ABC, abstractmethod

from storage.models import VideoSegment, VideoUnderstandingResult


class VideoProcessor(ABC):
    """视频处理器接口"""
    
    @abstractmethod
    def process_segment(self, segment: VideoSegment) -> VideoUnderstandingResult:
        """
        处理视频分段，返回理解结果
        
        Args:
            segment: 视频分段
        
        Returns:
            视频理解结果
        """
        pass

