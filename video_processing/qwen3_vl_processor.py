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
    """Qwen3-VL Plus 视频理解处理器"""
    
    def __init__(self, api_key: str = None, model: str = "qwen3-vl-plus", fps: float = 1.0):
        """
        初始化处理器
        
        Args:
            api_key: DashScope API Key，如果为 None 则从环境变量读取
            model: 模型名称，默认 qwen3-vl-plus
            fps: 视频抽帧率，表示每隔 1/fps 秒抽取一帧
        """
        self.api_key = api_key or os.getenv('DASHSCOPE_API_KEY')
        if not self.api_key:
            raise ValueError("未提供 DASHSCOPE_API_KEY，请在环境变量或参数中设置")
        
        self.model = model
        self.fps = fps
    
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
                messages=messages
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
        prompt = f"""请仔细分析这段实验室视频（时长约 {duration:.1f} 秒），并记录所有观察到的事件。

**重要要求**：
1. **必须记录所有人物出现和动作**：即使只是人物走进画面、坐下、操作手机或电脑，也要记录为事件
2. **观察人物外观特征**：衣服颜色、头发颜色等
3. **记录设备和药品的使用情况**：任何设备操作都要记录
4. **提取时间信息**：如果画面中有时间戳，请使用；否则使用相对时间

**输出格式**：必须以 JSON 格式输出，包含以下字段：
- event_id: 唯一事件 ID（格式：evt_001, evt_002...）
- start_time: 事件开始时间（ISO 格式，如 "2025-12-17T10:00:00"）
- end_time: 事件结束时间（ISO 格式）
- structured: 结构化数据对象
  - person: 人物信息对象
    - present: 是否有人（布尔值，true/false）
    - clothing_color: 衣服颜色（字符串，如"白色"、"蓝色"等）
    - hair_color: 头发颜色（字符串，可选）
  - action: 动作描述（字符串，如"走进画面"、"操作仪器"、"坐下"、"操作手机"等）
  - equipment: 使用的设备（字符串，可选，如"离心机"、"电脑"等）
  - chemicals: 使用的药品（字符串，可选）
  - remark: 备注（字符串，可选）
- raw_text: 事件的自然语言描述（字符串）

**输出示例**：
{{
  "events": [
    {{
      "event_id": "evt_001",
      "start_time": "2025-12-17T10:00:00",
      "end_time": "2025-12-17T10:00:15",
      "structured": {{
        "person": {{
          "present": true,
          "clothing_color": "白色",
          "hair_color": "黑色"
        }},
        "action": "走进画面",
        "remark": "人物从画面左侧进入"
      }},
      "raw_text": "一名穿白色衣服的人员在 10:00:00 走进画面"
    }},
    {{
      "event_id": "evt_002",
      "start_time": "2025-12-17T10:00:15",
      "end_time": "2025-12-17T10:01:00",
      "structured": {{
        "person": {{
          "present": true,
          "clothing_color": "白色"
        }},
        "action": "操作仪器",
        "equipment": "离心机"
      }},
      "raw_text": "人员在 10:00:15 开始操作离心机，持续约 45 秒"
    }}
  ]
}}

**特别注意**：
- 即使视频中只有人物出现、移动、坐下等简单动作，也要记录为事件
- 如果人物走出画面，也要记录为事件
- 如果人物回到画面，也要记录为新事件
- 必须输出有效的 JSON 格式，不能返回空的事件列表（除非视频中真的没有任何内容）"""
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
                    
                    # 构建 EventLog
                    event_log = EventLog(
                        event_id=event_id,
                        segment_id=segment.segment_id,
                        start_time=start_time,
                        end_time=end_time,
                        structured=event_data.get('structured', {}),
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

