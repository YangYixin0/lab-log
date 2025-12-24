"""Qwen3-VL Plus 视频理解处理器（动态上下文版本）"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from dotenv import load_dotenv
from dashscope import MultiModalConversation

from video_processing.interface import VideoProcessor
from storage.models import VideoSegment, VideoUnderstandingResult, EventLog
from context.appearance_cache import AppearanceCache
from context.event_context import EventContext
from context.prompt_builder import PromptBuilder

# 加载环境变量
load_dotenv()


@dataclass
class AppearanceUpdate:
    """外貌更新操作"""
    op: str  # add, update, merge
    target_person_id: str
    merge_from: Optional[str] = None
    appearance: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class ProcessingResult:
    """处理结果（包含事件和外貌更新）"""
    events: List[EventLog]
    appearance_updates: List[AppearanceUpdate]
    raw_response: str


class Qwen3VLPlusProcessor(VideoProcessor):
    """Qwen3-VL Plus 视频理解处理器（动态上下文版本）"""
    
    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        fps: float = 1.0,
        enable_thinking: bool = None,
        thinking_budget: int = None,
        appearance_cache: Optional[AppearanceCache] = None,
        event_context: Optional[EventContext] = None,
        max_recent_events: int = 20
    ):
        """
        初始化处理器
        
        Args:
            api_key: DashScope API Key，如果为 None 则从环境变量读取
            model: 模型名称，如果为 None 则从环境变量 QWEN_MODEL 读取，默认 "qwen3-vl-plus"
            fps: 视频抽帧率，表示每隔 1/fps 秒抽取一帧
            enable_thinking: 是否启用思考，如果为 None 则从环境变量 ENABLE_THINKING 读取，默认 True
            thinking_budget: 思考预算，如果为 None 则从环境变量 THINKING_BUDGET 读取，默认 8192 tokens
            appearance_cache: 人物外貌缓存，如果为 None 则创建默认实例
            event_context: 事件上下文，如果为 None 则创建默认实例
            max_recent_events: 最大最近事件数，默认 20
        """
        self.api_key = api_key or os.getenv('DASHSCOPE_API_KEY')
        if not self.api_key:
            raise ValueError("未提供 DASHSCOPE_API_KEY，请在环境变量或参数中设置")
        
        # 从环境变量读取模型配置，如果没有则使用默认值
        self.model = model or os.getenv('QWEN_MODEL', 'qwen3-vl-plus')
        
        # 从环境变量读取思考配置
        if enable_thinking is None:
            enable_thinking_str = os.getenv('ENABLE_THINKING', 'true')
            self.enable_thinking = enable_thinking_str.lower() in ('true', '1', 'yes', 'on')
        else:
            self.enable_thinking = enable_thinking
        
        if thinking_budget is None:
            thinking_budget_str = os.getenv('THINKING_BUDGET', '8192')
            try:
                self.thinking_budget = int(thinking_budget_str)
            except ValueError:
                self.thinking_budget = 8192
        else:
            self.thinking_budget = thinking_budget
        
        self.fps = fps
        
        # 动态上下文相关
        self.appearance_cache = appearance_cache or AppearanceCache()
        self.event_context = event_context
        self.max_recent_events = max_recent_events
        self.prompt_builder = PromptBuilder(max_recent_events)
        
        # 是否使用动态上下文（通过检查是否有 event_context 来判断）
        self._use_dynamic_context = event_context is not None
    
    def process_segment(self, segment: VideoSegment) -> VideoUnderstandingResult:
        """
        处理视频分段，返回理解结果
        
        Args:
            segment: 视频分段
        
        Returns:
            视频理解结果
        """
        video_path = segment.video_path
        
        # 构建视频文件路径（file:// 协议）
        if Path(video_path).is_absolute():
            video_url = f"file://{video_path}"
        else:
            video_url = f"file://{os.path.abspath(video_path)}"
        
        # 构建 prompt
        if self._use_dynamic_context:
            prompt = self._build_dynamic_prompt(segment)
        else:
            prompt = self._build_legacy_prompt(segment)
        
        # 调用 API
        messages = [
            {
                'role': 'user',
                'content': [
                    {'video': video_url, 'fps': self.fps},
                    {'text': prompt}
                ]
            }
        ]
        
        # 如果使用动态上下文，添加系统指令
        if self._use_dynamic_context:
            system_instruction = self.prompt_builder.build_system_instruction()
            messages.insert(0, {
                'role': 'system',
                'content': system_instruction
            })
        
        try:
            response = MultiModalConversation.call(
                api_key=self.api_key,
                model=self.model,
                messages=messages,
                stream=False,
                enable_thinking=self.enable_thinking,
                thinking_budget=self.thinking_budget
            )
            
            # 解析响应
            result_text = response["output"]["choices"][0]["message"].content[0]["text"]
            
            if self._use_dynamic_context:
                # 解析动态上下文响应
                processing_result = self._parse_dynamic_response(result_text, segment)
                
                # 应用外貌更新
                self._apply_appearance_updates(processing_result.appearance_updates)
                
                return VideoUnderstandingResult(
                    segment_id=segment.segment_id,
                    remark=result_text,
                    events=processing_result.events
                )
            else:
                # 使用旧的解析逻辑
                events = self._parse_legacy_response(result_text, segment)
                return VideoUnderstandingResult(
                    segment_id=segment.segment_id,
                    remark=result_text,
                    events=events
                )
        except Exception as e:
            raise RuntimeError(f"视频理解 API 调用失败: {e}")
    
    def process_segment_with_context(
        self,
        segment: VideoSegment,
        appearance_cache: AppearanceCache,
        recent_events: List[Dict[str, Any]],
        max_event_id: int
    ) -> ProcessingResult:
        """
        使用动态上下文处理视频分段
        
        Args:
            segment: 视频分段
            appearance_cache: 人物外貌缓存
            recent_events: 最近事件列表
            max_event_id: 当前最大事件编号数字
        
        Returns:
            处理结果（包含事件和外貌更新）
        """
        video_path = segment.video_path
        
        # 构建视频文件路径
        if Path(video_path).is_absolute():
            video_url = f"file://{video_path}"
        else:
            video_url = f"file://{os.path.abspath(video_path)}"
        
        # 获取最大人物编号
        max_person_id = appearance_cache.get_max_person_id_number()
        
        # 构建动态提示词
        prompt = self.prompt_builder.build_dynamic_prompt(
            segment=segment,
            qr_results=segment.qr_results,
            recent_events=recent_events,
            appearance_cache=appearance_cache,
            max_event_id=max_event_id,
            max_person_id=max_person_id
        )
        
        # 构建消息
        messages = [
            {
                'role': 'system',
                'content': self.prompt_builder.build_system_instruction()
            },
            {
                'role': 'user',
                'content': [
                    {'video': video_url, 'fps': self.fps},
                    {'text': prompt}
                ]
            }
        ]
        
        try:
            response = MultiModalConversation.call(
                api_key=self.api_key,
                model=self.model,
                messages=messages,
                stream=False,
                enable_thinking=self.enable_thinking,
                thinking_budget=self.thinking_budget
            )
            
            result_text = response["output"]["choices"][0]["message"].content[0]["text"]
            return self._parse_dynamic_response(result_text, segment)
            
        except Exception as e:
            raise RuntimeError(f"视频理解 API 调用失败: {e}")
    
    def _build_dynamic_prompt(self, segment: VideoSegment) -> str:
        """使用动态上下文构建提示词"""
        # 获取最近事件
        recent_events = []
        max_event_id = 0
        if self.event_context:
            recent_events = self.event_context.get_recent_events(self.max_recent_events)
            max_event_id = self.event_context.get_max_event_id_number()
        
        # 获取最大人物编号
        max_person_id = self.appearance_cache.get_max_person_id_number()
        
        return self.prompt_builder.build_dynamic_prompt(
            segment=segment,
            qr_results=segment.qr_results,
            recent_events=recent_events,
            appearance_cache=self.appearance_cache,
            max_event_id=max_event_id,
            max_person_id=max_person_id
        )
    
    def _parse_dynamic_response(
        self,
        response_text: str,
        segment: VideoSegment
    ) -> ProcessingResult:
        """
        解析动态上下文响应
        
        Args:
            response_text: API 返回的文本
            segment: 视频分段
        
        Returns:
            处理结果
        """
        events = []
        appearance_updates = []
        
        # 提取 JSON
        json_str = self._extract_json(response_text)
        if not json_str:
            return ProcessingResult(events=[], appearance_updates=[], raw_response=response_text)
        
        try:
            data = json.loads(json_str)
            
            # 解析事件
            events_data = data.get('events_to_append', [])
            for event_data in events_data:
                try:
                    event = self._parse_event(event_data, segment)
                    if event:
                        events.append(event)
                except Exception as e:
                    print(f"警告：解析事件失败: {e}")
                    continue
            
            # 解析外貌更新
            updates_data = data.get('appearance_updates', [])
            for update_data in updates_data:
                try:
                    update = self._parse_appearance_update(update_data)
                    if update:
                        appearance_updates.append(update)
                except Exception as e:
                    print(f"警告：解析外貌更新失败: {e}")
                    continue
            
        except json.JSONDecodeError as e:
            print(f"警告：无法解析 JSON 响应: {e}")
            print(f"响应文本: {response_text[:500]}")
        
        return ProcessingResult(
            events=events,
            appearance_updates=appearance_updates,
            raw_response=response_text
        )
    
    def _extract_json(self, text: str) -> Optional[str]:
        """从文本中提取 JSON"""
        # 尝试找到 JSON 代码块
        code_block_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if code_block_match:
            return code_block_match.group(1)
        
        # 尝试直接找到 JSON 对象
        json_start = text.find('{')
        json_end = text.rfind('}') + 1
        
        if json_start != -1 and json_end > json_start:
            return text[json_start:json_end]
        
        return None
    
    def _parse_event(self, event_data: Dict[str, Any], segment: VideoSegment) -> Optional[EventLog]:
        """解析单个事件"""
        try:
            # 解析时间
            start_time_str = event_data.get('start_time', '')
            end_time_str = event_data.get('end_time', '')
            
            try:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # 如果解析失败，使用当前时间
                start_time = datetime.now()
                end_time = datetime.now()
            
            # 获取事件 ID
            event_id = event_data.get('event_id', '')
            if not event_id:
                return None
            
            # 验证 event_type
            event_type = event_data.get('event_type', '')
            if event_type not in ['person', 'equipment-only', 'none']:
                print(f"警告：无效的 event_type '{event_type}'，必须是 'person'、'equipment-only' 或 'none'，已跳过事件 {event_id}")
                return None
            
            # 获取 person_ids（支持多人）
            person_ids = event_data.get('person_ids', [])
            if not isinstance(person_ids, list):
                print(f"警告：person_ids 必须是数组，已跳过事件 {event_id}")
                return None
            
            # 验证 equipment-only 和 none 事件的 person_ids 应为空
            if event_type in ['equipment-only', 'none'] and person_ids:
                print(f"警告：{event_type} 事件的 person_ids 应为空数组，已自动修正事件 {event_id}")
                person_ids = []
            
            # 构建 structured 数据（新格式）
            structured = {
                'person_ids': person_ids,
                'equipment': event_data.get('equipment', ''),
            }
            
            return EventLog(
                event_id=event_id,
                segment_id=segment.segment_id,
                start_time=start_time,
                end_time=end_time,
                event_type=event_type,
                structured=structured,
                raw_text=event_data.get('description', '')
            )
        except Exception as e:
            print(f"解析事件异常: {e}")
            return None
    
    def _parse_appearance_update(self, update_data: Dict[str, Any]) -> Optional[AppearanceUpdate]:
        """解析单个外貌更新"""
        op = update_data.get('op')
        target_person_id = update_data.get('target_person_id')
        
        if not op or not target_person_id:
            return None
        
        return AppearanceUpdate(
            op=op,
            target_person_id=target_person_id,
            merge_from=update_data.get('merge_from'),
            appearance=update_data.get('appearance'),
            user_id=update_data.get('user_id')
        )
    
    def _apply_appearance_updates(self, updates: List[AppearanceUpdate]) -> None:
        """应用外貌更新到缓存"""
        for update in updates:
            try:
                if update.op == 'add':
                    self.appearance_cache.add(
                        person_id=update.target_person_id,
                        appearance=update.appearance or '',
                        user_id=update.user_id
                    )
                elif update.op == 'update':
                    self.appearance_cache.update(
                        person_id=update.target_person_id,
                        appearance=update.appearance,
                        user_id=update.user_id
                    )
                elif update.op == 'merge':
                    if update.merge_from:
                        # 先执行合并
                        self.appearance_cache.merge(
                            merge_from=update.merge_from,
                            target_person_id=update.target_person_id
                        )
                        # 如果提供了新的外貌描述，更新目标记录
                        if update.appearance:
                            self.appearance_cache.update(
                                person_id=update.target_person_id,
                                appearance=update.appearance
                            )
            except Exception as e:
                print(f"警告：应用外貌更新失败 ({update.op} {update.target_person_id}): {e}")
    
    def _build_legacy_prompt(self, segment: VideoSegment) -> str:
        """构建旧版提示词（兼容模式）"""
        duration = segment.end_time - segment.start_time
        prompt = f"""请分析这段实验室视频（时长约 {duration:.1f} 秒），并记录所有观察到的事件。

**任务要求**：
1. 识别视频中的人物动作（使用了什么设备或工具或化学品）、设备运转状态，和相应的时间范围，记录为事件。
2. 关于时间
    - 根据视频画面左上角的时间戳水印 "yyyy-MM-dd Time: HH:MM:SS" 来判断时间。
    - 如果时间戳水印缺少日期，则使用2025-12-22作为日期。
3. 关于事件划分
    - 如果有多个人同时出现，将每个人的动作分开记录为事件。
    - 一个设备，如果有显示数值且似乎与人物动作无关，要单独记录为一个事件。
    - 没有显示数值且不被操作的设备，不记录为事件。
    - 不同人物或设备的事件的时间可以交叠，但同一人物或设备的事件时间不能交叠。
    - 同一个人的一些连续的人物事件，如果涉及同一个设备或没有涉及设备，要合并为一个事件。
4. 关于内容描述
    - 如果无法判断是什么设备或工具或化学品，就描述它的外观特征，如颜色、形状、大小等。
    - 描述设备仪表或设备显示屏上的数值及其变化，如果不清晰，则不描述具体数值。
    - 不描述手机和笔记本电脑显示屏上的内容。

**输出格式**：必须以 JSON 格式输出，包含以下字段：
- event_id: 唯一事件 ID（格式：evt_001, evt_002...）
- start_time: 事件开始时间（ISO 格式，如 "2025-12-17T10:00:00"）
- end_time: 事件结束时间（ISO 格式）
- event_type: 事件类型（字符串，如"person"、"equipment-only"）
- structured: 结构化数据对象
  - person: "person"事件中的对象人物
    - upper_clothing_color: 上衣颜色（字符串，可选，如"白色"、"蓝色"等，敏感信息，不可在其他字段中提及）
    - hair_color: 头发颜色（字符串，可选，敏感信息，不可在其他字段中提及）
    - action: 人物动作的简短描述（字符串，如"走进画面"、"操作设备"、"坐下"、"看手机"等）
  - equipment: "person"事件中对象人物使用的设备，或"equipment-only"事件中对象设备（字符串，可选，如"离心机"、"笔记本电脑"等）
  - tool: 对象人物使用的工具（字符串，可选，如"钳子"、"螺丝刀"、"镊子"等）
  - chemicals: 对象人物使用的化学品（字符串，可选，如"氧化铅"、"白色粉末"、"无水乙醇"、"无色液体"等）
- raw_text: 事件的自然语言描述，不提及具体时间和人物上衣颜色、头发颜色（字符串）

**输出示例**：
{{
  "events": [
    {{
      "event_id": "evt_001",
      "start_time": "2025-12-17T10:00:00",
      "end_time": "2025-12-17T10:00:20",
      "event_type": "person",
      "structured": {{
        "person": {{
          "upper_clothing_color": "白色",
          "hair_color": "黑色",
          "action": "看手机"
        }},
        "equipment": "手机"
      }},
      "raw_text": "对象人物坐在一张黑色椅子上，面向离心机，正在看手机屏幕。"
    }}
  ]
}}

**数据安全要求**：
- `structured.person.upper_clothing_color`（上衣颜色）和 `structured.person.hair_color`（头发颜色）字段在后续流程中会被加密存储
- **严禁**将这些敏感信息（上衣颜色、头发颜色）写入非加密字段，尤其是`raw_text`字段，否则会导致敏感信息泄露。
"""
        return prompt
    
    def _parse_legacy_response(self, response_text: str, segment: VideoSegment) -> List[EventLog]:
        """解析旧版响应（兼容模式）"""
        events = []
        
        json_str = self._extract_json(response_text)
        if not json_str:
            return events
        
        try:
            data = json.loads(json_str)
            events_data = data.get('events', [])
            
            if not events_data and isinstance(data, list):
                events_data = data
            
            for event_data in events_data:
                try:
                    start_time_str = event_data.get('start_time')
                    end_time_str = event_data.get('end_time')
                    
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                    except:
                        from datetime import timedelta
                        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                        start_time = base_date + timedelta(seconds=segment.start_time)
                        end_time = base_date + timedelta(seconds=segment.end_time)
                    
                    original_event_id = event_data.get('event_id', f"evt_{hash(str(event_data)) % 100000:05d}")
                    event_id = f"{segment.segment_id}_{original_event_id}"
                    
                    event_type = event_data.get('event_type')
                    structured = event_data.get('structured', {})
                    
                    event_log = EventLog(
                        event_id=event_id,
                        segment_id=segment.segment_id,
                        start_time=start_time,
                        end_time=end_time,
                        event_type=event_type,
                        structured=structured,
                        raw_text=event_data.get('raw_text', '')
                    )
                    events.append(event_log)
                except Exception as e:
                    print(f"警告：无法解析事件: {e}")
                    continue
        except json.JSONDecodeError as e:
            print(f"警告：无法解析 JSON 响应: {e}")
            print(f"响应文本: {response_text[:500]}")
        
        return events
