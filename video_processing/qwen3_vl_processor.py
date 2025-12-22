"""Qwen3-VL 视频理解处理器"""

import os
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from dashscope import MultiModalConversation

from video_processing.interface import VideoProcessor
from storage.models import VideoSegment, VideoUnderstandingResult, EventLog

# 加载环境变量
load_dotenv()


class Qwen3VLProcessor(VideoProcessor):
    """Qwen3-VL Flash 视频理解处理器"""
    
    def __init__(self, api_key: str = None, model: str = "qwen3-vl-flash", fps: float = 1.0, enable_thinking: bool = True, thinking_budget: int = 8192):
        """
        初始化处理器
        
        Args:
            api_key: DashScope API Key，如果为 None 则从环境变量读取
            model: 模型名称，默认 qwen3-vl-flash
            fps: 视频抽帧率，表示每隔 1/fps 秒抽取一帧
            enable_thinking: 是否启用思考，默认 True
            thinking_budget: 思考预算，默认 8192 tokens。qwen3-vl-flash最大支持 81920 tokens
        """
        self.api_key = api_key or os.getenv('DASHSCOPE_API_KEY')
        if not self.api_key:
            raise ValueError("未提供 DASHSCOPE_API_KEY，请在环境变量或参数中设置")
        
        self.model = model
        self.fps = fps
        self.enable_thinking = enable_thinking
        self.thinking_budget = thinking_budget
    
    def process_segment(self, segment: VideoSegment) -> VideoUnderstandingResult:
        """
        处理视频分段，返回理解结果
        
        Args:
            segment: 视频分段
        
        Returns:
            视频理解结果
        """
        video_path = segment.video_path
        
        # 如果 segment.video_path 包含时间范围信息（非临时文件），需要提取分段
        # 这里假设 segment.video_path 是完整的视频路径
        # 如果需要处理时间范围，需要先提取分段
        
        # 构建视频文件路径（file:// 协议）
        if Path(video_path).is_absolute():
            video_url = f"file://{video_path}"
        else:
            video_url = f"file://{os.path.abspath(video_path)}"
        
        # 构建 prompt
        prompt = self._build_prompt(segment)
        
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
            
            # 解析结构化结果
            events = self._parse_response(result_text, segment)
            
            return VideoUnderstandingResult(
                segment_id=segment.segment_id,
                remark=result_text,  # 保存原始响应作为备注
                events=events
            )
        except Exception as e:
            raise RuntimeError(f"视频理解 API 调用失败: {e}")
    
    def _build_prompt(self, segment: VideoSegment) -> str:
        """构建提示词"""
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
  - tool: 对象人物使用的工具（字符串，可选，如“钳子”、“螺丝刀”、“镊子”等）
  - chemicals: 对象人物使用的化学品（字符串，可选，如“氧化铅”、“白色粉末”、“无水乙醇”、“无色液体”等）
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
    }},
    {{
    "event_id": "evt_002",
      "start_time": "2025-12-17T10:00:00",
      "end_time": "2025-12-17T10:00:10",
      "event_type": "equipment-only",
      "structured": {{
        "equipment": "离心机"
      }},
      "raw_text": "离心机上的一个示数在20附近变化，另一个示数固定在19.5。"
    }},
    {{
      "event_id": "evt_003",
      "start_time": "2025-12-17T10:00:08",
      "end_time": "2025-12-17T10:00:10",
      "event_type": "person",
      "structured": {{
        "person": {{
          "upper_clothing_color": "橙色",
          "hair_color": "黑色",
          "action": "走进画面"
        }}
      }},
      "raw_text": "对象人物从左侧走进画面，走到离心机旁。"
    }},
    {{
      "event_id": "evt_004",
      "start_time": "2025-12-17T10:00:10",
      "end_time": "2025-12-17T10:00:56",
      "event_type": "person",
      "structured": {{
        "person": {{
          "upper_clothing_color": "橙色",
          "hair_color": "黑色",
          "action": "操作设备"
        }},
        "equipment": "离心机"
      }},
      "raw_text": "对象人物把一些离心管放入离心机。随后点击这台离心机面板上的按钮，离心机上的一个示数从20变化到大约30，另一个示数保持为19.5。"
    }},
    {{
      "event_id": "evt_005",
      "start_time": "2025-12-17T10:00:20",
      "end_time": "2025-12-17T10:00:56",
      "event_type": "person",
      "structured": {{
        "person": {{
          "upper_clothing_color": "白色",
          "hair_color": "黑色",
          "action": "观察"
        }}
      }},
      "raw_text": "对象人物站起来，放下手机，观察另一个人物操作离心机。"
    }}
  ]
}}

**数据安全要求**：
- `structured.person.upper_clothing_color`（上衣颜色）和 `structured.person.hair_color`（头发颜色）字段在后续流程中会被加密存储
- **严禁**将这些敏感信息（上衣颜色、头发颜色）写入非加密字段，尤其是`raw_text`字段，否则会导致敏感信息泄露。
"""
        return prompt
    
    def _parse_response(self, response_text: str, segment: VideoSegment) -> List[EventLog]:
        """
        解析 API 响应，转换为 EventLog 列表
        
        Args:
            response_text: API 返回的文本
            segment: 视频分段
        
        Returns:
            EventLog 列表
        """
        events = []
        
        # 尝试从响应中提取 JSON
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        
        if json_start == -1 or json_end == 0:
            # 如果没有找到 JSON，返回空列表
            return events
        
        try:
            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)
            
            events_data = data.get('events', [])
            
            # 如果没有 events 字段，尝试直接解析为事件数组
            if not events_data and isinstance(data, list):
                events_data = data
            
            for event_data in events_data:
                try:
                    # 解析时间
                    start_time_str = event_data.get('start_time')
                    end_time_str = event_data.get('end_time')
                    
                    # 如果时间字符串不完整，尝试解析
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                    except:
                        # 如果解析失败，使用分段的时间范围作为默认值
                        # 这里假设视频的开始时间是今天
                        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                        # 从时间戳中提取时分秒（如果可能）
                        start_time = base_date + timedelta(seconds=segment.start_time)
                        end_time = base_date + timedelta(seconds=segment.end_time)
                    
                    # 生成 event_id（添加分段标识符确保唯一性）
                    original_event_id = event_data.get('event_id', f"evt_{uuid.uuid4().hex[:8]}")
                    # 使用分段 ID 作为前缀，确保不同分段的事件 ID 唯一
                    event_id = f"{segment.segment_id}_{original_event_id}"
                    
                    # 提取 event_type（作为独立字段，不放入 structured）
                    event_type = event_data.get('event_type')
                    structured = event_data.get('structured', {})
                    
                    # 构建 EventLog
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
                    # 跳过无法解析的事件
                    print(f"警告：无法解析事件: {e}")
                    continue
        except json.JSONDecodeError as e:
            print(f"警告：无法解析 JSON 响应: {e}")
            print(f"响应文本: {response_text[:500]}")
        
        return events

