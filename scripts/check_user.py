#!/usr/bin/env python3
"""检查数据库中的用户"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from storage.seekdb_client import SeekDBClient

def main():
    print("检查数据库中的用户...")
    print()
    
    try:
        with SeekDBClient() as db:
            # 查询所有用户
            sql = "SELECT user_id, username, role, password_hash IS NOT NULL as has_password FROM users"
            with db.connection.cursor() as cursor:
                cursor.execute(sql)
                users = cursor.fetchall()
            
            if not users:
                print("❌ 数据库中没有用户")
                print()
                print("请运行以下命令初始化数据库并创建admin用户：")
                print("  python scripts/init_database.py")
                return
            
            print(f"✓ 找到 {len(users)} 个用户：")
            print()
            for user in users:
                user_dict = dict(user)
                print(f"  用户ID: {user_dict['user_id']}")
                print(f"  用户名: {user_dict['username']}")
                print(f"  角色: {user_dict['role']}")
                print(f"  密码: {'已设置' if user_dict['has_password'] else '未设置'}")
                print()
            
            # 检查admin用户
            admin_user = db.get_user_by_username('admin')
            if admin_user:
                print("✓ admin用户存在")
                if admin_user.get('password_hash'):
                    print("✓ admin用户已设置密码")
                    print()
                    print("可以使用以下凭据登录：")
                    print("  用户名: admin")
                    print("  密码: admin")
                else:
                    print("❌ admin用户未设置密码")
                    print()
                    print("请运行以下命令重新初始化数据库：")
                    print("  python scripts/init_database.py")
            else:
                print("❌ admin用户不存在")
                print()
                print("请运行以下命令初始化数据库并创建admin用户：")
                print("  python scripts/init_database.py")
                
    except Exception as e:
        print(f"❌ 查询失败: {e}")
        print()
        print("可能的原因：")
        print("  1. SeekDB服务未启动")
        print("  2. 数据库连接配置错误")
        print()
        print("请检查：")
        print("  1. 确保SeekDB容器正在运行：docker ps | grep seekdb")
        print("  2. 检查.env文件中的数据库配置")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()

