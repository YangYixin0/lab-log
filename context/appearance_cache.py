"""人物外貌缓存管理器：使用并查集维护合并关系"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class AppearanceRecord:
    """人物外貌记录"""
    person_id: str              # p1, p2... 模型分配，新增必须 > 现存最大
    appearance: str             # 详细外貌描述（常见+稀有特征）
    user_id: Optional[str] = None  # 关联的用户ID（来自二维码）
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class UnionFind:
    """并查集实现，用于管理人物编号的合并关系"""
    
    def __init__(self):
        self.parent: Dict[str, str] = {}
    
    def find(self, x: str) -> str:
        """查找根节点（带路径压缩）"""
        if x not in self.parent:
            self.parent[x] = x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    
    def union(self, small: str, large: str) -> None:
        """
        合并：将小编号合并到大编号
        
        Args:
            small: 被合并的小编号（merge_from）
            large: 目标大编号（target_person_id）
        """
        root_small = self.find(small)
        root_large = self.find(large)
        if root_small != root_large:
            # 始终将小的指向大的
            self.parent[root_small] = root_large
    
    def get_all_aliases(self, person_id: str) -> List[str]:
        """获取某个主编号的所有别名（被合并到它的编号）"""
        root = self.find(person_id)
        aliases = []
        for node, parent in self.parent.items():
            if self.find(node) == root and node != root:
                aliases.append(node)
        return sorted(aliases, key=lambda x: self._extract_number(x))
    
    def get_roots(self) -> List[str]:
        """获取所有主编号（根节点）"""
        roots = set()
        for node in self.parent:
            roots.add(self.find(node))
        return sorted(list(roots), key=lambda x: self._extract_number(x))
    
    def _extract_number(self, person_id: str) -> int:
        """从 person_id (如 p1, p23) 提取数字"""
        match = re.search(r'\d+', person_id)
        return int(match.group()) if match else 0
    
    def to_dict(self) -> Dict[str, str]:
        """序列化为字典"""
        return dict(self.parent)
    
    def load_from_dict(self, data: Dict[str, str]) -> None:
        """从字典加载"""
        self.parent = dict(data)


class AppearanceCache:
    """人物外貌缓存管理器"""
    
    def __init__(self):
        self.records: Dict[str, AppearanceRecord] = {}  # person_id -> record
        self.union_find = UnionFind()
    
    def add(self, person_id: str, appearance: str, user_id: Optional[str] = None) -> None:
        """
        追加新人物记录
        
        Args:
            person_id: 人物编号（必须 > 现存最大）
            appearance: 详细外貌描述
            user_id: 可选的用户ID
        """
        if person_id in self.records:
            raise ValueError(f"人物编号 {person_id} 已存在，请使用 update 方法")
        
        max_id = self.get_max_person_id_number()
        new_id_num = self._extract_number(person_id)
        if max_id is not None and new_id_num <= max_id:
            raise ValueError(f"新增编号 {person_id} 必须大于现存最大编号 p{max_id}")
        
        self.records[person_id] = AppearanceRecord(
            person_id=person_id,
            appearance=appearance,
            user_id=user_id
        )
        # 初始化并查集节点
        self.union_find.find(person_id)
    
    def update(self, person_id: str, appearance: Optional[str] = None, 
               user_id: Optional[str] = None) -> None:
        """
        更新人物记录（可补充外貌描述、补全 user_id）
        
        Args:
            person_id: 人物编号
            appearance: 新的外貌描述（如提供则替换）
            user_id: 用户ID（如提供则更新）
        """
        # 找到实际的主编号
        root_id = self.union_find.find(person_id)
        
        if root_id not in self.records:
            raise ValueError(f"人物编号 {person_id}（主编号 {root_id}）不存在")
        
        record = self.records[root_id]
        if appearance is not None:
            record.appearance = appearance
        if user_id is not None:
            record.user_id = user_id
    
    def merge(self, merge_from: str, target_person_id: str) -> None:
        """
        合并人物记录（小编号合并到大编号）
        
        Args:
            merge_from: 被合并的小编号
            target_person_id: 目标大编号
        """
        from_num = self._extract_number(merge_from)
        to_num = self._extract_number(target_person_id)
        
        if from_num >= to_num:
            raise ValueError(
                f"merge_from ({merge_from}) 必须小于 target_person_id ({target_person_id})"
            )
        
        # 执行并查集合并
        self.union_find.union(merge_from, target_person_id)
        
        # 如果被合并的记录有 user_id 但目标没有，则继承
        from_root = self.union_find.find(merge_from)
        if merge_from in self.records and from_root in self.records:
            from_record = self.records[merge_from]
            to_record = self.records[from_root]
            if from_record.user_id and not to_record.user_id:
                to_record.user_id = from_record.user_id
    
    def get_for_prompt(self) -> Tuple[List[Dict], List[Dict]]:
        """
        获取用于提示词的外貌表数据
        
        Returns:
            (主记录列表, 别名列表)
            - 主记录：[{person_id, appearance, user_id}, ...]
            - 别名：[{alias, main_person_id}, ...]
        """
        roots = self.union_find.get_roots()
        main_records = []
        all_aliases = []
        
        for root in roots:
            if root in self.records:
                record = self.records[root]
                main_records.append({
                    "person_id": record.person_id,
                    "appearance": record.appearance,
                    "user_id": record.user_id
                })
                
                # 收集别名
                aliases = self.union_find.get_all_aliases(root)
                for alias in aliases:
                    all_aliases.append({
                        "alias": alias,
                        "main_person_id": root
                    })
        
        return main_records, all_aliases
    
    def get_max_person_id(self) -> Optional[str]:
        """返回当前最大编号字符串（如 'p23'）"""
        max_num = self.get_max_person_id_number()
        return f"p{max_num}" if max_num is not None else None
    
    def get_max_person_id_number(self) -> Optional[int]:
        """返回当前最大编号数字"""
        if not self.records:
            return None
        max_num = 0
        for person_id in self.records:
            num = self._extract_number(person_id)
            if num > max_num:
                max_num = num
        return max_num if max_num > 0 else None
    
    def _extract_number(self, person_id: str) -> int:
        """从 person_id (如 p1, p23) 提取数字"""
        match = re.search(r'\d+', person_id)
        return int(match.group()) if match else 0
    
    def get_record(self, person_id: str) -> Optional[AppearanceRecord]:
        """获取人物记录（自动解析合并关系）"""
        root_id = self.union_find.find(person_id)
        return self.records.get(root_id)
    
    def dump_to_file(self, path: str) -> None:
        """
        保存缓存到 JSONL 文件
        
        Args:
            path: 文件路径
        """
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "records": {
                pid: {
                    "person_id": r.person_id,
                    "appearance": r.appearance,
                    "user_id": r.user_id,
                    "created_at": r.created_at
                }
                for pid, r in self.records.items()
            },
            "union_find": self.union_find.to_dict(),
            "dump_time": datetime.now().isoformat()
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def load_from_file(self, path: str) -> bool:
        """
        从文件加载缓存
        
        Args:
            path: 文件路径
        
        Returns:
            是否成功加载
        """
        file_path = Path(path)
        if not file_path.exists():
            return False
        
        try:
            # 检查文件是否为空
            file_size = file_path.stat().st_size
            if file_size == 0:
                print(f"[Context]: 外貌缓存为空")
                return False
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    print(f"[Context]: 外貌缓存为空")
                    return False
                
                data = json.loads(content)
            
            self.records.clear()
            for pid, r in data.get("records", {}).items():
                self.records[pid] = AppearanceRecord(
                    person_id=r["person_id"],
                    appearance=r["appearance"],
                    user_id=r.get("user_id"),
                    created_at=r.get("created_at", datetime.now().isoformat())
                )
            
            self.union_find.load_from_dict(data.get("union_find", {}))
            return True
        except json.JSONDecodeError as e:
            # JSON 解析错误，可能是文件为空或格式错误
            if "Expecting value" in str(e) or "line 1 column 1" in str(e):
                print(f"[Context]: 外貌缓存为空")
            else:
                print(f"[Context]: 加载外貌缓存失败（JSON 格式错误）: {e}")
            return False
        except Exception as e:
            print(f"[Context]: 加载外貌缓存失败: {e}")
            return False
    
    def get_record_count(self) -> int:
        """获取记录总数"""
        return len(self.records)
    
    def get_root_count(self) -> int:
        """获取主编号数量（去重后）"""
        return len(self.union_find.get_roots())
    
    def clear(self) -> None:
        """清空缓存"""
        self.records.clear()
        self.union_find = UnionFind()


