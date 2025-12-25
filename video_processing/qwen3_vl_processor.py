"""Qwen3-VL 视频理解处理器工厂（根据环境变量选择 Flash 或 Plus）"""

import os
from typing import Optional

from dotenv import load_dotenv
from video_processing.interface import VideoProcessor
from context.appearance_cache import AppearanceCache
from context.event_context import EventContext

# 加载环境变量
load_dotenv()

# 延迟导入，避免循环依赖
from video_processing.qwen3_vl_flash_processor import Qwen3VLFlashProcessor
from video_processing.qwen3_vl_plus_processor import Qwen3VLPlusProcessor


def create_qwen_processor(
    api_key: str = None,
    model: str = None,
    fps: Optional[float] = None,
    enable_thinking: bool = None,
    thinking_budget: int = None,
    appearance_cache: Optional[AppearanceCache] = None,
    event_context: Optional[EventContext] = None,
    max_recent_events: int = 20
) -> VideoProcessor:
    """
    创建 Qwen3-VL 视频处理器（根据环境变量或参数选择 Flash 或 Plus）
    
    Args:
        api_key: DashScope API Key，如果为 None 则从环境变量读取
        model: 模型名称，如果为 None 则从环境变量 QWEN_MODEL 读取
        fps: 视频抽帧率，表示每隔 1/fps 秒抽取一帧，如果为 None 则从环境变量 VIDEO_FPS 读取，默认 1.0，如果为默认值 1.0 则从环境变量 VIDEO_FPS 读取
        enable_thinking: 是否启用思考，如果为 None 则从环境变量 ENABLE_THINKING 读取
        thinking_budget: 思考预算，如果为 None 则从环境变量 THINKING_BUDGET 读取
        appearance_cache: 人物外貌缓存，如果为 None 则创建默认实例
        event_context: 事件上下文，如果为 None 则创建默认实例
        max_recent_events: 最大最近事件数，默认 20
    
    Returns:
        VideoProcessor 实例（Qwen3VLFlashProcessor 或 Qwen3VLPlusProcessor）
    """
    # 确定使用的模型
    if model is None:
        model = os.getenv('QWEN_MODEL', 'qwen3-vl-flash')
    
    # 从环境变量读取 fps 配置，如果没有则使用参数或默认值
    if fps is None:
        fps_str = os.getenv('VIDEO_FPS', '1.0')
        try:
            fps = float(fps_str)
        except ValueError:
            fps = 1.0
    
    # 根据模型名称选择处理器
    if 'plus' in model.lower() or model == 'qwen3-vl-plus':
        return Qwen3VLPlusProcessor(
            api_key=api_key,
            model=model,
            fps=fps,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
            appearance_cache=appearance_cache,
            event_context=event_context,
            max_recent_events=max_recent_events
        )
    else:
        # 默认使用 Flash
        return Qwen3VLFlashProcessor(
            api_key=api_key,
            model=model,
            fps=fps,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
            appearance_cache=appearance_cache,
            event_context=event_context,
            max_recent_events=max_recent_events
        )


# 为了向后兼容，提供一个默认的类名
# 使用环境变量 QWEN_MODEL 来决定使用哪个处理器
class Qwen3VLProcessor:
    """
    Qwen3-VL 视频理解处理器（兼容类）
    
    根据环境变量 QWEN_MODEL 自动选择使用 Flash 或 Plus 处理器
    默认使用 Flash 处理器
    """
    
    def __new__(
        cls,
        api_key: str = None,
        model: str = None,
        fps: Optional[float] = None,
        enable_thinking: bool = None,
        thinking_budget: int = None,
        appearance_cache: Optional[AppearanceCache] = None,
        event_context: Optional[EventContext] = None,
        max_recent_events: int = 20
    ):
        """创建处理器实例"""
        return create_qwen_processor(
            api_key=api_key,
            model=model,
            fps=fps,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
            appearance_cache=appearance_cache,
            event_context=event_context,
            max_recent_events=max_recent_events
        )
