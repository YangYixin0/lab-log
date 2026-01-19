"""OpenRouter 视频理解处理器（支持 Gemini 2.5 Flash，使用 /v1/responses 接口）"""

import os
import json
import re
import base64
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from dotenv import load_dotenv

from video_processing.interface import VideoProcessor
from storage.models import VideoSegment, VideoUnderstandingResult, EventLog
from context.appearance_cache import AppearanceCache
from context.event_context import EventContext
from context.prompt_builder import PromptBuilder
from utils.segment_time_parser import extract_date_from_segment_id

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


class OpenRouterProcessor(VideoProcessor):
    """OpenRouter 视频理解处理器（支持 Gemini 2.5 Flash）"""
    
    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        fps: Optional[float] = None,
        enable_thinking: bool = None,
        thinking_budget: int = None,
        appearance_cache: Optional[AppearanceCache] = None,
        event_context: Optional[EventContext] = None,
        max_recent_events: int = 20
    ):
        """
        初始化处理器
        
        Args:
            api_key: OpenRouter API Key，如果为 None 则从环境变量读取
            model: 模型名称，如果为 None 则从环境变量 VIDEO_UNDERSTANDING_MODEL 读取，默认 "google/gemini-2.5-flash"
            fps: 视频抽帧率
            enable_thinking: 是否启用思考
            thinking_budget: 思考预算
            appearance_cache: 人物外貌缓存
            event_context: 事件上下文
            max_recent_events: 最大最近事件数
        """
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("未提供 OPENROUTER_API_KEY，请在环境变量或参数中设置")
        
        self.base_url = "https://openrouter.ai/api/v1/responses"
        self.model = model or os.getenv('VIDEO_UNDERSTANDING_MODEL', 'google/gemini-2.5-flash')
        
        # 思考配置
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

        # 采样参数
        temp_str = os.getenv('VL_TEMPERATURE', '0.1')
        try:
            self.temperature = float(temp_str)
        except ValueError:
            self.temperature = 0.1
        
        top_p_str = os.getenv('VL_TOP_P', '0.7')
        try:
            self.top_p = float(top_p_str)
        except ValueError:
            self.top_p = 0.7
            
        # 动态上下文
        self.appearance_cache = appearance_cache or AppearanceCache()
        self.event_context = event_context
        self.max_recent_events = max_recent_events
        self.prompt_builder = PromptBuilder(max_recent_events)
        self._use_dynamic_context = event_context is not None

    def _write_thinking_log(self, segment_id: str, thinking: Optional[str]) -> None:
        """将模型思考内容写入日志文件"""
        log_path = Path("logs_debug/event_logs_thinking.jsonl")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        log_entry = {
            "segment_id": segment_id,
            "thinking": thinking or "未获取到思考内容",
            "timestamp": datetime.now().isoformat()
        }
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def _encode_video_to_base64(self, video_path: str) -> str:
        """将视频文件编码为 base64"""
        with open(video_path, "rb") as video_file:
            return base64.b64encode(video_file.read()).decode('utf-8')

    def process_segment(self, segment: VideoSegment) -> VideoUnderstandingResult:
        """处理视频分段（不支持动态上下文的旧版接口）"""
        if self._use_dynamic_context:
            # 如果提供了上下文，优先使用带上下文的方法
            return self.process_segment_with_context(
                segment, self.appearance_cache, [], 0
            ).events # 简化
            
        video_base64 = self._encode_video_to_base64(segment.video_path)
        prompt = self._build_legacy_prompt(segment)
        
        try:
            thinking, result_text = self._call_api(video_base64, prompt)
            self._write_thinking_log(segment.segment_id, thinking)
            
            events = self._parse_legacy_response(result_text, segment)
            
            return VideoUnderstandingResult(
                segment_id=segment.segment_id,
                remark=result_text,
                events=events
            )
        except Exception as e:
            raise RuntimeError(f"OpenRouter API 调用失败: {e}")

    def process_segment_with_context(
        self,
        segment: VideoSegment,
        appearance_cache: AppearanceCache,
        recent_events: List[Dict[str, Any]],
        max_event_id: int
    ) -> ProcessingResult:
        """使用动态上下文处理视频分段"""
        video_base64 = self._encode_video_to_base64(segment.video_path)
        max_person_id = appearance_cache.get_max_person_id_number()
        
        prompt = self.prompt_builder.build_dynamic_prompt(
            segment=segment,
            qr_results=segment.qr_results,
            recent_events=recent_events,
            appearance_cache=appearance_cache,
            max_event_id=max_event_id,
            max_person_id=max_person_id
        )
        
        system_instruction = self.prompt_builder.build_system_instruction()
        
        try:
            thinking, result_text = self._call_api(video_base64, prompt, system_instruction)
            self._write_thinking_log(segment.segment_id, thinking)
            
            processing_result = self._parse_dynamic_response(result_text, segment)
            return processing_result
            
        except Exception as e:
            raise RuntimeError(f"OpenRouter API 调用失败: {e}")

    def _call_api(self, video_base64: str, prompt: str, system_instruction: Optional[str] = None) -> Tuple[Optional[str], str]:
        """封装 OpenRouter API 调用 (使用 /v1/responses)"""
        
        # 构造输入
        input_items = []
        if system_instruction:
            input_items.append({
                "type": "message",
                "role": "system",
                "content": system_instruction
            })
            
        input_items.append({
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": prompt
                },
                {
                    "type": "input_video",
                    "video_url": f"data:video/mp4;base64,{video_base64}"
                }
            ]
        })
        
        # 构造请求体
        payload = {
            "model": self.model,
            "input": input_items,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "reasoning": {
                "enabled": self.enable_thinking,
                "max_tokens": self.thinking_budget
            },
            "provider": {
                "order": ["Google (Vertex)", "Google"]
            }
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(self.base_url, json=payload, headers=headers, timeout=180)
        response.raise_for_status()
        
        data = response.json()
        
        thinking = None
        result_text = ""
        
        # 遍历输出数组
        for item in data.get("output", []):
            item_type = item.get("type")
            if item_type == "reasoning":
                # 提取思考内容
                content_list = item.get("content", [])
                thinking_parts = [c.get("text", "") for c in content_list if c.get("type") == "reasoning_text"]
                thinking = "\n".join(thinking_parts)
            elif item_type == "message":
                # 提取最终文本
                content_list = item.get("content", [])
                text_parts = [c.get("text", "") for c in content_list if c.get("type") == "output_text"]
                result_text = "\n".join(text_parts)
                
        return thinking, result_text

    def _parse_dynamic_response(self, response_text: str, segment: VideoSegment) -> ProcessingResult:
        """解析动态上下文响应"""
        events = []
        appearance_updates = []
        
        json_str = self._extract_json(response_text)
        if not json_str:
            return ProcessingResult(events=[], appearance_updates=[], raw_response=response_text)
        
        try:
            data = json.loads(json_str)
            
            events_data = data.get('events_to_append', [])
            for event_data in events_data:
                try:
                    event = self._parse_event(event_data, segment)
                    if event:
                        events.append(event)
                except Exception as e:
                    print(f"警告：解析事件失败: {e}")
                    continue
            
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
            
        return ProcessingResult(
            events=events,
            appearance_updates=appearance_updates,
            raw_response=response_text
        )

    def _extract_json(self, text: str) -> Optional[str]:
        """从文本中提取 JSON"""
        code_block_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if code_block_match:
            return code_block_match.group(1)
        
        json_start = text.find('{')
        json_end = text.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            return text[json_start:json_end]
        return None

    def _parse_event(self, event_data: Dict[str, Any], segment: VideoSegment) -> Optional[EventLog]:
        """解析单个事件"""
        try:
            start_time_str = event_data.get('start_time', '')
            end_time_str = event_data.get('end_time', '')
            
            try:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
            except:
                start_time = datetime.now()
                end_time = datetime.now()
            
            event_id = event_data.get('event_id', '')
            if not event_id: return None
            
            event_type = event_data.get('event_type', '')
            if event_type not in ['person', 'equipment-only', 'none']: return None
            
            person_ids = event_data.get('person_ids', [])
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
        except:
            return None

    def _parse_appearance_update(self, update_data: Dict[str, Any]) -> Optional[AppearanceUpdate]:
        """解析单个外貌更新"""
        op = update_data.get('op')
        target_person_id = update_data.get('target_person_id')
        if not op or not target_person_id: return None
        
        return AppearanceUpdate(
            op=op,
            target_person_id=target_person_id,
            merge_from=update_data.get('merge_from'),
            appearance=update_data.get('appearance'),
            user_id=update_data.get('user_id')
        )

    def _build_legacy_prompt(self, segment: VideoSegment) -> str:
        """构建旧版提示词"""
        duration = segment.end_time - segment.start_time
        return f"请分析这段约 {duration:.1f} 秒的实验室视频，输出 JSON 格式的事件日志。"

    def _parse_legacy_response(self, response_text: str, segment: VideoSegment) -> List[EventLog]:
        """解析旧版响应"""
        return []

    def _apply_appearance_updates(self, updates: List[AppearanceUpdate]) -> None:
        """应用外貌更新到缓存"""
        for update in updates:
            try:
                if update.op == 'add':
                    self.appearance_cache.add(update.target_person_id, update.appearance or '', update.user_id)
                elif update.op == 'update':
                    self.appearance_cache.update(update.target_person_id, update.appearance, update.user_id)
                elif update.op == 'merge' and update.merge_from:
                    self.appearance_cache.merge(update.merge_from, update.target_person_id)
                    if update.appearance:
                        self.appearance_cache.update(update.target_person_id, update.appearance)
            except Exception as e:
                print(f"警告：应用外貌更新失败: {e}")
