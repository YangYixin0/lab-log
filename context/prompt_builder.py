"""动态提示词构建器：基于上下文构建视频理解提示"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from storage.models import VideoSegment
from context.appearance_cache import AppearanceCache


class PromptBuilder:
    """动态提示词构建器"""
    
    def __init__(self, max_recent_events: int = 20):
        """
        初始化提示词构建器
        
        Args:
            max_recent_events: 最大最近事件数
        """
        self.max_recent_events = max_recent_events
    
    def build_dynamic_prompt(
        self,
        segment: VideoSegment,
        qr_results: List[Dict[str, Any]],
        recent_events: List[Dict[str, Any]],
        appearance_cache: AppearanceCache,
        max_event_id: int,
        max_person_id: Optional[int]
    ) -> str:
        """
        构建动态提示词
        
        Args:
            segment: 视频分段
            qr_results: 二维码识别结果
            recent_events: 最近事件列表
            appearance_cache: 人物外貌缓存
            max_event_id: 当前最大事件编号数字
            max_person_id: 当前最大人物编号数字（可能为 None）
        
        Returns:
            构建好的提示词文本
        """
        # 格式化各部分内容
        qr_section = self._format_qr_results(qr_results)
        events_section = self._format_recent_events(recent_events)
        appearance_section = self._format_appearance_table(appearance_cache)
        
        # 计算新编号的起始值
        next_event_id = max_event_id + 1
        next_person_id = (max_person_id or 0) + 1
        
        prompt = f"""请分析这段实验室视频，结合已有的上下文信息，输出续写的事件日志和人物外貌记录更新。

## 时间戳
- 视频中的时间戳水印格式为 "yyyy-MM-dd Time: hh:mm:ss"
- 如果时间戳水印缺少日期，使用2025-1-1作为日期

## 二维码识别结果
{qr_section}

## 最近事件记录（参考描述风格，共 {len(recent_events)} 条）
{events_section}

## 人物外貌表（已全量给出）
{appearance_section}

## 任务要求

### 1. 事件识别
- 识别视频中的人物动作（操作设备或化学品）、设备状态变化
- 根据视频画面左上角的时间戳水印确定时间
- **event_type 只能是 "person" 或 "equipment-only" 或 "none"**，不能使用其他值
- person 事件中，如果人物操作了什么设备，那么 equipment 字段应当记录该设备名称。如果人物没有操作设备，那么 equipment 字段应当为空字符串。
- **同一个人连续未操作设备或操作同一个设备时，应当合并为一个事件，描述可以长一些。**
- **注意描述人物将物品从哪个容器取出，或者放进哪个容器。** 如果看不清是什么物品，就描述为“某个物品”。
- 如果画面内存在多个相似的容器，例如多个相似的抽屉，那么描述中应当借助画面中有唯一性、一般不会转移的物品和方位词来辅助限定容器对象。
- **注意描述人物使用的化学品上的文字**。如果看不清，则描述化学品的颜色、物质状态。
- 多个人物同时出现时，如果人物动作关系密切，则记录为多人共同参与的事件（person_ids 包含多个人物编号），否则分开记录各自的事件。
- 关注设备显示的数值。如果设备示数与人物动作无关，那么单独记录为 equipment-only 事件（person_ids 为空数组）。每个能显示数值的设备都应当被记录。只要能看清设备示数，不论示数是否变化，都不应当记为 none 事件。
- 不同事件的时间范围可以有部分或完全重叠，例如，如果画面中同时出现某个人物和某个显示数值的设备，而且人物动作和设备状态变化是独立的，那么这两个事件应当分开记录而且有部分或完全的重叠时间范围。

### 2. 人物识别与外貌匹配
- **优先重用已有外貌记录**：当前画面中的人物如与已有外貌描述匹配（尤其是稀有特征匹配），应使用已有的 person_id
- 外貌描述要从头到脚详细描述，常见特点和稀有特点都要描述。看不清的特征不要描述。
- **稀有特征**（如特殊发色、独特配饰、鲜艳衣服颜色、衣服上的显眼图案、特殊体型等）的区分价值更高
- **常见特征**（如白色实验服/白大褂、黑色头发、戴眼镜）一致仅是匹配的必要条件，不能仅凭常见特征就判定为同一人
- **稀有特征**一致是合并的强信号，但仍需确认无冲突。若缺少稀有特征区分，不要轻易合并已有的外貌记录
- 实验室人物频繁穿上或脱下手套，因此区分人物时不要借助手套特征来考虑。
- 发现全新人物时，追加新记录

### 3. 二维码用户关联
- 当二维码识别结果中的时间戳与视频画面时间接近时，观察该时刻画面中展示二维码的人物
- 如果该人物的外貌与已有外貌记录匹配，则更新该外貌记录，补充 user_id
- 如果该人物的外貌与已有外貌记录不匹配，则追加新记录，带有 user_id

### 4. 外貌记录操作
- **add**: 基于当前视频画面发现新人物，那么追加记录（新编号必须 > 现存最大）
- **update**: 基于当前视频画面更新已记录的人物的外貌特征或 user_id
- **merge**: 基于当前视频画面发现两个记录是同一人，那么将小编号合并到大编号
  - 合并时，将小编号的所有特征融合到大编号的描述中
  - merge_from 必须小于 target_person_id

### 5. 编号分配规则
- 新事件编号必须从 evt_{next_event_id:05d} 开始递增
- start_time 在先的事件先描述。如果两个事件的 start_time 相同，则随意。
- 新人物编号必须从 p{next_person_id} 开始递增

## 输出格式
必须输出以下 JSON 格式：

```json
{{
  "events_to_append": [
    {{
      "event_id": "evt_xxxxx",
      "start_time": "2025-12-24T10:00:00",
      "end_time": "2025-12-24T10:00:20",
      "event_type": "person",
      "person_ids": ["p3"],
      "description": "人物 p3 向本摄像头展示二维码。"
    }},
    {{
      "event_id": "evt_xxxxx",
      "start_time": "2025-12-24T10:00:00",
      "end_time": "2025-12-24T10:00:35",
      "event_type": "person",
      "person_ids": ["p6", "p7"],
      "equipment": "离心机",
      "description": "人物 p6 抬起离心机上盖，人物 p7 蹲下将试管放入离心机中。"
    }},
    {{
      "event_id": "evt_xxxxx",
      "start_time": "2025-12-24T10:00:00",
      "end_time": "2025-12-24T10:00:55",
      "event_type": "equipment-only",
      "person_ids": [],
      "equipment": "恒温箱",
      "description": "恒温箱显示屏显示温度为 37.5°C，温度保持稳定，未有人物操作。"
    }},
    {{
      "event_id": "evt_xxxxx",
      "start_time": "2025-12-24T10:00:00",
      "end_time": "2025-12-24T10:00:55",
      "event_type": "none",
      "person_ids": [],
      "equipment": "",
      "description": "画面中无人物活动，无设备显示数值变化。"
    }}
  ],
  "appearance_updates": [
    {{
      "op": "add",
      "target_person_id": "p7",
      "appearance": "短黑发，戴黑框眼镜，穿白色实验服，内搭蓝色格子衬衫，黑色休闲裤，白色运动鞋，左手腕戴银色手表。",
      "user_id": null
    }},
    {{
      "op": "update",
      "target_person_id": "p3",
      "appearance": "长黑发扎马尾，戴透明护目镜，穿白色实验服，内搭粉色T恤，蓝色牛仔裤，白色平底鞋，右手无名指戴银色戒指。",
      "user_id": "350a9666b94f4e40"
    }},
    {{
      "op": "merge",
      "target_person_id": "p6",
      "merge_from": "p2",
      "appearance": "短棕发，未佩戴眼镜，穿白色实验服，内搭灰色毛衣（有独特的红色条纹），深蓝色西裤，棕色皮鞋，左耳有小耳钉。"
    }}
  ]
}}
```

## 注意事项
- 事件描述中不要包含具体的人物外貌特征和 user_id，这些信息保存在外貌表中
- equipment-only 和 none 事件的 person_ids 应为空数组 []
- 如果视频中没有人物，但是有设备显示数值，那么描述并返回 equipment-only 事件
- 如果视频中既没有人物活动，也没有设备显示数值，那么返回 none 事件（person_ids 为空数组，equipment 为空字符串）
- 如果没有外貌更新，appearance_updates 返回空数组
"""
        return prompt
    
    def _format_qr_results(self, qr_results: List[Dict[str, Any]]) -> str:
        """格式化二维码识别结果"""
        if not qr_results:
            return "（本视频片段无二维码识别结果）"
        
        lines = []
        for qr in qr_results:
            user_id = qr.get('user_id', '未知')
            # 将毫秒时间戳转换为秒精度的可读时间
            detected_at = qr.get('detected_at', '')
            if not detected_at:
                detected_at_ms = qr.get('detected_at_ms')
                if detected_at_ms:
                    dt = datetime.fromtimestamp(detected_at_ms / 1000)
                    detected_at = dt.strftime('%Y-%m-%dT%H:%M:%S')
            
            # 如果 detected_at 已经是 ISO 格式，截取到秒
            if detected_at and '.' in detected_at:
                detected_at = detected_at.split('.')[0]
            
            # confidence = qr.get('confidence', 0)
            lines.append(f"- 用户ID: {user_id}, 识别时间: {detected_at}")
        
        return "\n".join(lines)
    
    def _format_recent_events(self, events: List[Dict[str, Any]]) -> str:
        """格式化最近事件记录"""
        if not events:
            return "（暂无事件记录）"
        
        lines = []
        for event in events:
            person_ids = event.get('person_ids', [])
            person_str = ", ".join(person_ids) if person_ids else "-"
            equipment = event.get('equipment', '') or "-"
            
            line = (
                f"- {event.get('event_id', '')} | "
                f"{event.get('start_time', '')} ~ {event.get('end_time', '')} | "
                f"{event.get('event_type', '')} | "
                f"人物: {person_str} | "
                f"设备: {equipment} | "
                f"{event.get('description', '')}"
            )
            lines.append(line)
        
        return "\n".join(lines)
    
    def _format_appearance_table(self, appearance_cache: AppearanceCache) -> str:
        """格式化人物外貌表"""
        main_records, aliases = appearance_cache.get_for_prompt()
        
        if not main_records:
            return "（暂无人物外貌记录）"
        
        lines = []
        
        # 主记录
        lines.append("### 人物记录")
        for record in main_records:
            user_id_str = f", 用户ID: {record['user_id']}" if record.get('user_id') else ""
            lines.append(f"- {record['person_id']}: {record['appearance']}{user_id_str}")
        
        # 别名
        if aliases:
            lines.append("\n### 编号别名（已合并）")
            for alias_info in aliases:
                lines.append(f"- {alias_info['alias']} -> {alias_info['main_person_id']}")
        
        return "\n".join(lines)
    
    def build_system_instruction(self) -> str:
        """
        构建系统指令
        
        Returns:
            系统指令文本
        """
        return """你是一个实验室视频分析助手，负责分析视频内容并生成结构化的事件日志。

你需要：
1. 仔细观察视频中的人物动作和设备状态
2. 根据时间戳水印确定事件的时间范围
3. 将观察结果与已有的上下文（事件记录、人物外貌表）关联
4. 输出续写的事件和外貌更新，格式必须为指定的 JSON 格式

关键原则：
- 准确识别时间戳，精确到秒
- 优先重用已有的人物编号，避免创建重复记录
- 外貌匹配时，稀有特征的权重高于常见特征
- 不在事件描述中提及人物外貌信息（如上衣颜色、头发颜色等），这些信息保存在外貌表中
- 只输出 JSON，不要输出其他内容"""

