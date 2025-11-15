#!/usr/bin/env python3
"""
WebSocket服务器，接收ESP32发送的摄像头MJPEG数据，
保存图片并统计FPS
支持通过命令行控制Arduino开始/停止采集
"""
import asyncio
import websockets
import os
import sys
from datetime import datetime
from pathlib import Path
import glob

# 服务器配置
HOST = "0.0.0.0"
PORT = 50001

# 图片存储配置
IMAGES_DIR = Path(__file__).parent / "images"
MAX_IMAGES = 200  # 最多保存200张图片

# FPS统计
frame_count = 0
last_fps_time = None
fps_counter = 0
frame_sequence = 0  # 全局帧序号计数器

# 客户端连接管理
connected_websocket = None  # 当前连接的WebSocket客户端

def ensure_images_dir():
    """确保图片目录存在"""
    IMAGES_DIR.mkdir(exist_ok=True)
    return IMAGES_DIR

def get_next_frame_number():
    """获取下一个帧序号（使用全局计数器）"""
    global frame_sequence
    frame_sequence += 1
    return frame_sequence

def cleanup_old_images():
    """删除最旧的图片，保持最多MAX_IMAGES张"""
    pattern = str(IMAGES_DIR / "frame_*.jpg")
    files = glob.glob(pattern)
    
    if len(files) <= MAX_IMAGES:
        return
    
    # 按修改时间排序，删除最旧的
    files.sort(key=lambda x: os.path.getmtime(x))
    files_to_delete = files[:-MAX_IMAGES]
    
    for f in files_to_delete:
        try:
            os.remove(f)
        except OSError:
            pass

def save_frame(image_data, frame_number):
    """保存帧图片"""
    timestamp = datetime.now()
    filename = f"frame_{timestamp.strftime('%Y%m%d_%H%M%S')}_{frame_number:03d}.jpg"
    filepath = IMAGES_DIR / filename
    
    try:
        with open(filepath, 'wb') as f:
            f.write(image_data)
        return True
    except Exception as e:
        print(f"保存图片失败: {e}")
        return False

async def handle_client(websocket):
    """处理客户端连接"""
    global frame_count, last_fps_time, fps_counter, frame_sequence, connected_websocket
    
    client_address = websocket.remote_address
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 新客户端连接: {client_address[0]}:{client_address[1]}")
    
    # 保存当前连接的WebSocket
    connected_websocket = websocket
    
    # 确保图片目录存在
    ensure_images_dir()
    
    # 重置FPS统计和帧序号
    frame_count = 0
    fps_counter = 0
    frame_sequence = 0
    last_fps_time = datetime.now()
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 可以使用以下命令控制采集:")
    print("  start  - 开始采集")
    print("  stop   - 停止采集")
    print("  status - 查询状态")
    print("  help   - 显示帮助")
    
    try:
        async for message in websocket:
            # 接收二进制数据（JPEG图片）
            if isinstance(message, bytes):
                # 保存图片
                frame_count += 1
                fps_counter += 1
                
                # 获取帧序号
                frame_number = get_next_frame_number()
                
                # 保存图片
                if save_frame(message, frame_number):
                    # 清理旧图片
                    cleanup_old_images()
                
                # 每秒统计并打印FPS
                current_time = datetime.now()
                time_diff = (current_time - last_fps_time).total_seconds()
                
                if time_diff >= 1.0:  # 每秒更新一次
                    fps = fps_counter / time_diff
                    timestamp = current_time.strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[{timestamp}] FPS: {fps:.2f} (总帧数: {frame_count})")
                    
                    # 重置计数器
                    fps_counter = 0
                    last_fps_time = current_time
            else:
                # 收到文本消息（Arduino的确认或状态消息）
                message_str = message.decode('utf-8') if isinstance(message, bytes) else message
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Arduino响应: {message_str}")
                
    except websockets.exceptions.ConnectionClosed:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 客户端 {client_address[0]}:{client_address[1]} 断开连接")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 总共接收 {frame_count} 帧")
        connected_websocket = None
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 处理客户端 {client_address[0]}:{client_address[1]} 时发生错误: {e}")
        connected_websocket = None

async def read_commands():
    """读取命令行输入并发送控制命令"""
    global connected_websocket
    
    loop = asyncio.get_event_loop()
    
    while True:
        try:
            # 使用asyncio在后台线程中读取输入
            command = await loop.run_in_executor(None, input)
            command = command.strip().lower()
            
            if not command:
                continue
            
            if command == "help":
                print("\n可用命令:")
                print("  start  - 开始采集和上传摄像头数据")
                print("  stop   - 停止采集和上传")
                print("  status - 查询Arduino当前状态")
                print("  help   - 显示此帮助信息")
                print("  quit   - 退出程序\n")
                continue
            
            if command == "quit" or command == "exit":
                print("正在退出...")
                os._exit(0)
            
            if connected_websocket is None:
                print("错误: 没有客户端连接，无法发送命令")
                continue
            
            # 发送命令到Arduino
            try:
                await connected_websocket.send(command)
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"[{timestamp}] 已发送命令: {command}")
            except Exception as e:
                print(f"发送命令失败: {e}")
                connected_websocket = None
                
        except EOFError:
            # 输入流关闭
            break
        except Exception as e:
            print(f"读取命令时出错: {e}")
            await asyncio.sleep(0.1)

async def main():
    """启动WebSocket服务器"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 启动WebSocket服务器...")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 监听地址: {HOST}:{PORT}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 图片保存路径: {IMAGES_DIR}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 最多保存图片数: {MAX_IMAGES}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 等待客户端连接...")
    print("-" * 60)
    
    # 启动命令行输入任务
    command_task = asyncio.create_task(read_commands())
    
    async with websockets.serve(handle_client, HOST, PORT):
        await asyncio.Future()  # 永久运行

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 服务器已停止")
