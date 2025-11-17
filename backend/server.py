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
arduino_websocket = None  # Arduino客户端连接（/esp）
frontend_websocket = None  # 前端开发者控制台连接（/dev）

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
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] [服务器] 保存图片失败: {e}")
        return False

async def send_log_to_frontend(message: str):
    """向前端发送日志消息"""
    global frontend_websocket
    if frontend_websocket is not None:
        try:
            await frontend_websocket.send(message)
        except (websockets.exceptions.ConnectionClosed, Exception):
            # 如果发送失败（连接已关闭或其他错误），则认为前端连接已失效
            frontend_websocket = None

async def handle_arduino(websocket):
    """处理Arduino客户端连接（/esp）"""
    global frame_count, last_fps_time, fps_counter, frame_sequence, arduino_websocket
    
    client_address = websocket.remote_address
    ts = datetime.now().strftime('%H:%M:%S')
    log_msg = f"[{ts}] [Arduino] 新连接: {client_address[0]}:{client_address[1]}"
    print(log_msg)
    try:
        await send_log_to_frontend(log_msg)
    except Exception:
        pass  # 日志发送失败不影响主流程
    
    # 保存Arduino连接
    arduino_websocket = websocket
    
    # 确保图片目录存在
    ensure_images_dir()
    
    # 重置FPS统计和帧序号
    frame_count = 0
    fps_counter = 0
    frame_sequence = 0
    last_fps_time = datetime.now()
    
    ts = datetime.now().strftime('%H:%M:%S')
    help_msg = f"[{ts}] [服务器] 可以使用以下命令控制采集:\n  start  - 开始采集\n  stop   - 停止采集\n  status - 查询状态\n  help   - 显示帮助"
    print(help_msg)
    try:
        await send_log_to_frontend(help_msg)
    except Exception:
        pass  # 日志发送失败不影响主流程
    
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
                    timestamp = current_time.strftime('%H:%M:%S')
                    log_msg = f"[{timestamp}] [Arduino] FPS: {fps:.2f} (总帧数: {frame_count})"
                    print(log_msg)
                    try:
                        await send_log_to_frontend(log_msg)
                    except Exception:
                        pass  # 日志发送失败不影响主流程
                    
                    # 重置计数器
                    fps_counter = 0
                    last_fps_time = current_time
            else:
                # 收到文本消息（ACK/STATUS）
                message_str = message.decode('utf-8') if isinstance(message, bytes) else message
                ts = datetime.now().strftime('%H:%M:%S')
                log_msg = f"[{ts}] [Arduino] {message_str}"
                print(log_msg)
                try:
                    await send_log_to_frontend(log_msg)
                except Exception:
                    pass  # 日志发送失败不影响主流程
                
    except websockets.exceptions.ConnectionClosed:
        ts = datetime.now().strftime('%H:%M:%S')
        log_msg1 = f"[{ts}] [Arduino] 断开连接: {client_address[0]}:{client_address[1]}"
        log_msg2 = f"[{ts}] [Arduino] 总共接收 {frame_count} 帧"
        print(log_msg1)
        print(log_msg2)
        try:
            await send_log_to_frontend(log_msg1)
            await send_log_to_frontend(log_msg2)
        except Exception:
            pass  # 日志发送失败不影响主流程
        arduino_websocket = None
    except Exception as e:
        ts = datetime.now().strftime('%H:%M:%S')
        log_msg = f"[{ts}] [Arduino] 处理连接时发生错误: {e}"
        print(log_msg)
        try:
            await send_log_to_frontend(log_msg)
        except Exception:
            pass  # 日志发送失败不影响主流程
        arduino_websocket = None

async def handle_frontend(websocket):
    """处理前端开发者控制台连接（/dev）"""
    global frontend_websocket, arduino_websocket
    
    client_address = websocket.remote_address
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] [前端] 新连接: {client_address[0]}:{client_address[1]}")
    
    # 保存前端连接
    frontend_websocket = websocket
    
    try:
        async for message in websocket:
            # 前端发送文本消息（命令）
            if isinstance(message, bytes):
                message_str = message.decode('utf-8')
            else:
                message_str = message
            
            ts = datetime.now().strftime('%H:%M:%S')
            print(f"[{ts}] [服务器] 收到命令: {message_str}")
            
            # 转发命令给Arduino
            if arduino_websocket is None:
                error_msg = f"[{ts}] [服务器] 错误: Arduino未连接，无法转发命令"
                print(error_msg)
                try:
                    await send_log_to_frontend(error_msg)
                except Exception:
                    pass  # 日志发送失败不影响主流程
            else:
                try:
                    await arduino_websocket.send(message_str)
                    success_msg = f"[{ts}] [服务器] 已转发命令给Arduino: {message_str}"
                    print(success_msg)
                    try:
                        await send_log_to_frontend(success_msg)
                    except Exception:
                        pass  # 日志发送失败不影响主流程
                except (websockets.exceptions.ConnectionClosed, Exception) as e:
                    error_msg = f"[{ts}] [服务器] 转发命令失败: {e}"
                    print(error_msg)
                    try:
                        await send_log_to_frontend(error_msg)
                    except Exception:
                        pass  # 日志发送失败不影响主流程
                    arduino_websocket = None
                
    except websockets.exceptions.ConnectionClosed:
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] [前端] 断开连接: {client_address[0]}:{client_address[1]}")
        frontend_websocket = None
    except Exception as e:
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] [前端] 处理连接时发生错误: {e}")
        frontend_websocket = None

async def handle_client(websocket):
    """根据路径路由到不同的处理函数"""
    # 在 websockets 15.0+ 中，路径通过 request.path 获取
    path = websocket.request.path
    if path == "/esp":
        await handle_arduino(websocket)
    elif path == "/dev":
        await handle_frontend(websocket)
    else:
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] [服务器] 拒绝未知路径的连接: {path}")
        await websocket.close(code=1008, reason="Unknown endpoint")

async def read_commands():
    """读取命令行输入并发送控制命令"""
    global arduino_websocket
    
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
                ts = datetime.now().strftime('%H:%M:%S')
                print(f"[{ts}] [服务器] 正在退出...")
                os._exit(0)
            
            if arduino_websocket is None:
                ts = datetime.now().strftime('%H:%M:%S')
                print(f"[{ts}] [终端] 错误: Arduino未连接，无法发送命令")
                continue
            
            # 发送命令到Arduino
            try:
                await arduino_websocket.send(command)
                timestamp = datetime.now().strftime('%H:%M:%S')
                print(f"[{timestamp}] [终端] 已发送命令: {command}")
            except Exception as e:
                ts = datetime.now().strftime('%H:%M:%S')
                print(f"[{ts}] [终端] 发送命令失败: {e}")
                arduino_websocket = None
                
        except EOFError:
            # 输入流关闭
            break
        except Exception as e:
            ts = datetime.now().strftime('%H:%M:%S')
            print(f"[{ts}] [终端] 读取命令时出错: {e}")
            await asyncio.sleep(0.1)

async def main():
    """启动WebSocket服务器"""
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] [服务器] 启动WebSocket服务器...")
    print(f"[{ts}] [服务器] 监听地址: {HOST}:{PORT}")
    print(f"[{ts}] [服务器] 图片保存路径: {IMAGES_DIR}")
    print(f"[{ts}] [服务器] 最多保存图片数: {MAX_IMAGES}")
    print(f"[{ts}] [服务器] 支持的endpoint:")
    print(f"[{ts}] [服务器]   /esp - Arduino摄像头客户端")
    print(f"[{ts}] [服务器]   /dev - 开发者前端控制台")
    print(f"[{ts}] [服务器] 等待客户端连接...")
    print("-" * 60)
    
    # 启动命令行输入任务
    command_task = asyncio.create_task(read_commands())
    
    async with websockets.serve(handle_client, HOST, PORT):
        await asyncio.Future()  # 永久运行

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"\n[{ts}] [服务器] 服务器已停止")
