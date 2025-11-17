#!/usr/bin/env python3
"""
图片管理器：负责图片存储、清理和帧序号管理
"""
import os
import glob
from datetime import datetime
from pathlib import Path


class ImageManager:
    """管理图片存储、清理和帧序号"""
    
    def __init__(self, images_dir: Path = None, max_images: int = 200):
        """
        初始化图片管理器
        
        Args:
            images_dir: 图片存储目录，默认为当前文件所在目录的images子目录
            max_images: 最多保存的图片数量，默认200
        """
        if images_dir is None:
            images_dir = Path(__file__).parent / "images"
        self.images_dir = Path(images_dir)
        self.max_images = max_images
        self.frame_sequence = 0  # 帧序号计数器
        
        # 确保图片目录存在
        self.ensure_images_dir()
    
    def ensure_images_dir(self) -> Path:
        """确保图片目录存在"""
        self.images_dir.mkdir(exist_ok=True)
        return self.images_dir
    
    def get_next_frame_number(self) -> int:
        """获取下一个帧序号"""
        self.frame_sequence += 1
        return self.frame_sequence
    
    def reset_frame_sequence(self):
        """重置帧序号计数器"""
        self.frame_sequence = 0
    
    def cleanup_old_images(self):
        """删除最旧的图片，保持最多max_images张"""
        pattern = str(self.images_dir / "frame_*.jpg")
        files = glob.glob(pattern)
        
        if len(files) <= self.max_images:
            return
        
        # 按修改时间排序，删除最旧的
        files.sort(key=lambda x: os.path.getmtime(x))
        files_to_delete = files[:-self.max_images]
        
        for f in files_to_delete:
            try:
                os.remove(f)
            except OSError:
                pass
    
    def save_frame(self, image_data: bytes, frame_number: int = None) -> bool:
        """
        保存帧图片
        
        Args:
            image_data: 图片二进制数据
            frame_number: 帧序号，如果为None则自动获取下一个序号
        
        Returns:
            bool: 保存是否成功
        """
        if frame_number is None:
            frame_number = self.get_next_frame_number()
        
        timestamp = datetime.now()
        filename = f"frame_{timestamp.strftime('%Y%m%d_%H%M%S')}_{frame_number:03d}.jpg"
        filepath = self.images_dir / filename
        
        try:
            with open(filepath, 'wb') as f:
                f.write(image_data)
            return True
        except Exception as e:
            ts = datetime.now().strftime('%H:%M:%S')
            print(f"[{ts}] [服务器] 保存图片失败: {e}")
            return False

