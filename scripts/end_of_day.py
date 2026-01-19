#!/usr/bin/env python3
"""
日终处理脚本（骨架）

功能：
1. 加载当天外貌缓存
2. 并查集去重压缩
3. 加密 user_id 并写入数据库
4. 更新数据库中事件的 person_ids（将被合并编号替换为主编号）
5. 触发 indexing

使用方法：
    python scripts/end_of_day.py [--date YYYY-MM-DD] [--dry-run]
"""

import sys
import argparse
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set, Optional

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from context.appearance_cache import AppearanceCache
from storage.seekdb_client import SeekDBClient
from log_writer.encryption_service import FieldEncryptionService


def load_appearance_cache(date: datetime) -> AppearanceCache:
    """
    加载外貌缓存 (appearances.json)
    
    Args:
        date: 日期 (已废弃，现在统一读取 appearances.json)
    
    Returns:
        AppearanceCache 实例
    """
    cache = AppearanceCache()
    cache_path = Path("logs_debug") / "appearances.json"
    
    if cache_path.exists():
        loaded = cache.load_from_file(str(cache_path))
        if loaded:
            print(f"[加载] 外貌缓存加载成功，名义日期: {cache.nominal_date}，共 {cache.get_record_count()} 条记录，"
                  f"{cache.get_root_count()} 个主编号")
        else:
            print("[警告] 外貌缓存加载失败")
    else:
        print(f"[警告] 外貌缓存文件不存在: {cache_path}")
    
    return cache


def compress_union_find(cache: AppearanceCache) -> Dict[str, str]:
    """
    并查集去重压缩：生成最终的编号映射
    
    Args:
        cache: 外貌缓存
    
    Returns:
        编号映射字典 {原编号: 主编号}
    """
    mapping = {}
    
    # 获取所有记录的编号
    for person_id in cache.records:
        root = cache.union_find.find(person_id)
        if person_id != root:
            mapping[person_id] = root
    
    if mapping:
        print(f"[压缩] 需要替换的编号映射: {len(mapping)} 条")
        for old_id, new_id in sorted(mapping.items()):
            print(f"  {old_id} -> {new_id}")
    else:
        print("[压缩] 无需替换，所有编号均为主编号")
    
    return mapping


def update_events_person_ids(
    db_client: SeekDBClient,
    mapping: Dict[str, str],
    date: datetime,
    dry_run: bool = False
) -> int:
    """
    更新数据库中事件的 person_ids（将被合并编号替换为主编号）
    
    Args:
        db_client: 数据库客户端
        mapping: 编号映射字典
        date: 日期
        dry_run: 是否只预览不执行
    
    Returns:
        更新的事件数量
    """
    if not mapping:
        return 0
    
    # TODO: 实现实际的数据库更新逻辑
    # 1. 查询当天所有事件
    # 2. 检查 structured.person_ids 是否包含需要替换的编号
    # 3. 替换并更新
    
    print(f"[更新] {'预览模式 - ' if dry_run else ''}更新事件中的 person_ids...")
    
    # 占位实现
    updated_count = 0
    
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    
    # 示例：查询并更新逻辑（需要根据实际数据库 schema 实现）
    # events = db_client.query_event_logs(start_time=day_start.isoformat(), end_time=day_end.isoformat())
    # for event in events:
    #     structured = json.loads(event['structured'])
    #     person_ids = structured.get('person_ids', [])
    #     new_person_ids = [mapping.get(pid, pid) for pid in person_ids]
    #     if new_person_ids != person_ids:
    #         if not dry_run:
    #             # 更新数据库
    #             pass
    #         updated_count += 1
    
    print(f"[更新] 完成，{'将' if dry_run else '已'}更新 {updated_count} 个事件")
    return updated_count


def encrypt_and_save_appearances(
    cache: AppearanceCache,
    db_client: SeekDBClient,
    dry_run: bool = False
) -> int:
    """
    加密外貌记录并写入数据库
    
    逻辑：
    1. 如果记录有 user_id，使用该用户的公钥加密 appearance 和 user_id
    2. 如果记录没有 user_id，则明文存储
    3. 加密产生的 DEK 存入密钥表，user_id 留空
    
    Args:
        cache: 外貌缓存
        db_client: 数据库客户端
        dry_run: 是否只预览不执行
    
    Returns:
        保存的记录数量
    """
    print(f"[入库] {'预览模式 - ' if dry_run else ''}处理外貌记录并写入数据库...")
    
    # 初始化加密服务
    encryption_service = FieldEncryptionService()
    
    # 获取主记录
    main_records, aliases = cache.get_for_prompt()
    nominal_date = cache.nominal_date
    if not nominal_date:
        print("[错误] 缓存中未发现名义日期，无法入库")
        return 0
    
    saved_count = 0
    for record in main_records:
        person_id = record['person_id']
        appearance = record['appearance']
        target_user_id = record.get('user_id')
        
        # 使用包含日期的复合 ID 格式作为加密上下文 ID
        appearance_event_id = f"appearance_{person_id}_{nominal_date}"
        
        db_user_id: Optional[str] = None
        db_appearance: Optional[str] = None
        
        if not dry_run:
            try:
                if target_user_id:
                    # 1. 尝试获取该用户的公钥
                    try:
                        user_public_key = db_client.get_user_public_key(target_user_id)
                    except Exception as e:
                        print(f"  [错误] 关键隐私失败: 用户 {target_user_id} 存在但系统中未找到其公钥，无法加密隐私数据。详细错误: {e}")
                        sys.exit(1) # 明确要求报错中止流程

                    # 2. 加密 appearance
                    encrypted_appearance, encrypted_dek_appearance = encryption_service.encrypt_field_value(
                        event_id=appearance_event_id,
                        field_path="appearance",
                        value=appearance,
                        user_id=target_user_id,
                        public_key_pem=user_public_key
                    )
                    
                    # 3. 保存 appearance 的加密密钥 (user_id 字段留空)
                    db_client.insert_field_encryption_key(
                        ref_id=person_id,
                        ref_date=nominal_date,
                        field_path="appearance",
                        user_id=None,
                        encrypted_dek=encrypted_dek_appearance
                    )
                    
                    # 4. 加密 user_id 本身
                    encrypted_user_id, encrypted_dek_user_id = encryption_service.encrypt_field_value(
                        event_id=appearance_event_id,
                        field_path="user_id",
                        value=target_user_id,
                        user_id=target_user_id,
                        public_key_pem=user_public_key
                    )
                    
                    # 5. 保存 user_id 的加密密钥 (user_id 字段留空)
                    db_client.insert_field_encryption_key(
                        ref_id=person_id,
                        ref_date=nominal_date,
                        field_path="user_id",
                        user_id=None,
                        encrypted_dek=encrypted_dek_user_id
                    )
                    
                    db_user_id = encrypted_user_id
                    db_appearance = encrypted_appearance
                    status_msg = f"已加密（用户={target_user_id}）"
                else:
                    # 无 user_id，明文存储
                    db_user_id = None
                    db_appearance = appearance
                    status_msg = "明文存储"

                # 6. 插入外貌记录
                db_client.insert_appearance_record(
                    person_id=person_id,
                    date=nominal_date,
                    user_id=db_user_id,
                    appearance=db_appearance
                )

                saved_count += 1
                print(f"  {person_id}: {status_msg}, 外貌长度={len(appearance)}")

            except Exception as e:
                print(f"  [错误] 处理 {person_id} 失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        else:
            # 预览模式
            saved_count += 1
            if target_user_id:
                print(f"  {person_id}: 将使用用户 {target_user_id} 的公钥加密")
            else:
                print(f"  {person_id}: 将以明文存储")
    
    print(f"[入库] 完成，{'将' if dry_run else '已'}保存 {saved_count} 条记录")
    return saved_count


def trigger_indexing(date: datetime, dry_run: bool = False) -> None:
    """
    触发索引（分块和嵌入）
    
    Args:
        date: 日期
        dry_run: 是否只预览不执行
    """
    print(f"[索引] {'预览模式 - ' if dry_run else ''}触发索引...")
    
    if dry_run:
        print("[索引] 预览模式，跳过实际索引")
        return
    
    # 调用 index_events.py 脚本
    script_path = project_root / "scripts" / "index_events.py"
    
    if not script_path.exists():
        print(f"[错误] 索引脚本不存在: {script_path}")
        return
    
    try:
        print("[索引] 开始执行索引脚本...")
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=3600  # 1小时超时
        )
        
        if result.returncode == 0:
            print("[索引] 索引脚本执行成功")
            if result.stdout:
                # 打印最后几行输出
                lines = result.stdout.strip().split('\n')
                for line in lines[-5:]:
                    if line.strip():
                        print(f"  {line}")
        else:
            print(f"[错误] 索引脚本执行失败（返回码: {result.returncode}）")
            if result.stderr:
                print(f"  错误信息: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        print("[错误] 索引脚本执行超时（超过1小时）")
    except Exception as e:
        print(f"[错误] 执行索引脚本失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="日终处理脚本")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="处理日期（格式：YYYY-MM-DD），默认为今天"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览不执行实际操作"
    )
    
    args = parser.parse_args()
    
    # 解析日期
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(f"错误：无效的日期格式: {args.date}，请使用 YYYY-MM-DD")
            sys.exit(1)
    else:
        target_date = datetime.now()
    
    print(f"=" * 60)
    print(f"日终处理脚本")
    print(f"处理日期: {target_date.strftime('%Y-%m-%d')}")
    print(f"模式: {'预览' if args.dry_run else '执行'}")
    print(f"=" * 60)
    
    # 1. 加载外貌缓存
    print("\n[步骤 1/5] 加载外貌缓存")
    cache = load_appearance_cache(target_date)
    
    if cache.get_record_count() == 0:
        print("\n[完成] 无外貌记录需要处理")
        return
    
    # 2. 并查集压缩
    print("\n[步骤 2/5] 并查集去重压缩")
    mapping = compress_union_find(cache)
    
    # 3. 更新事件中的 person_ids
    print("\n[步骤 3/5] 更新事件中的 person_ids")
    try:
        db_client = SeekDBClient()
        updated_count = update_events_person_ids(db_client, mapping, target_date, args.dry_run)
    except Exception as e:
        print(f"[错误] 数据库连接失败: {e}")
        db_client = None
        updated_count = 0
    
    # 4. 加密并保存外貌记录
    print("\n[步骤 4/5] 加密并保存外貌记录")
    if db_client:
        saved_count = encrypt_and_save_appearances(cache, db_client, args.dry_run)
    else:
        print("[跳过] 数据库不可用")
        saved_count = 0
    
    # 5. 触发索引
    print("\n[步骤 5/5] 触发索引")
    trigger_indexing(target_date, args.dry_run)
    
    # 清理
    if db_client:
        db_client.close()
    
    print("\n" + "=" * 60)
    print("日终处理完成")
    print(f"  - 外貌记录: {cache.get_record_count()} 条")
    print(f"  - 主编号数: {cache.get_root_count()} 个")
    print(f"  - 编号映射: {len(mapping)} 条")
    print(f"  - 事件更新: {updated_count} 个")
    print(f"  - 入库记录: {saved_count} 条")
    print("=" * 60)


if __name__ == "__main__":
    main()


