"""动态上下文模块：人物外貌缓存、事件上下文、提示词构建"""

from context.appearance_cache import AppearanceCache, AppearanceRecord
from context.event_context import EventContext
from context.prompt_builder import PromptBuilder

__all__ = [
    'AppearanceCache',
    'AppearanceRecord',
    'EventContext',
    'PromptBuilder',
]
