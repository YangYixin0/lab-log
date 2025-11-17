#!/usr/bin/env python3
"""
WebSocket服务器，接收ESP32发送的摄像头MJPEG数据，
保存图片并统计FPS
支持通过命令行控制Arduino开始/停止采集
"""
import asyncio
import websockets
import os
from datetime import datetime
from pathlib import Path

from image_manager import ImageManager
from fps_monitor import FPSMonitor


class WebSocketServer:
    """WebSocket服务器主类"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 50001, 
                 images_dir: Path = None, max_images: int = 200):
        """
        初始化WebSocket服务器
        
        Args:
            host: 服务器监听地址
            port: 服务器监听端口
            images_dir: 图片存储目录
            max_images: 最多保存的图片数量
        """
        self.host = host
        self.port = port
        
        # 初始化图片管理器和FPS监控器
        self.image_manager = ImageManager(images_dir, max_images)
        self.fps_monitor = FPSMonitor()
        
        # 客户端连接管理
        self.arduino_websocket = None  # Arduino客户端连接（/esp）
        self.frontend_websocket = None  # 前端开发者控制台连接（/dev）
    
    async def send_log_to_frontend(self, message: str):
        """向前端发送日志消息"""
        if self.frontend_websocket is not None:
            try:
                await self.frontend_websocket.send(message)
            except (websockets.exceptions.ConnectionClosed, Exception):
                # 如果发送失败（连接已关闭或其他错误），则认为前端连接已失效
                self.frontend_websocket = None
    
    async def handle_arduino(self, websocket):
        """处理Arduino客户端连接（/esp）"""
        client_address = websocket.remote_address
        ts = datetime.now().strftime('%H:%M:%S')
        log_msg = f"[{ts}] [Arduino] 新连接: {client_address[0]}:{client_address[1]}"
        print(log_msg)
        try:
            await self.send_log_to_frontend(log_msg)
        except Exception:
            pass  # 日志发送失败不影响主流程
        
        # 保存Arduino连接
        self.arduino_websocket = websocket
        
        # 重置FPS统计和帧序号
        self.fps_monitor.reset()
        self.image_manager.reset_frame_sequence()
        
        ts = datetime.now().strftime('%H:%M:%S')
        help_msg = f"[{ts}] [服务器] 可以使用以下命令控制采集:\n  start  - 开始采集\n  stop   - 停止采集\n  status - 查询状态\n  help   - 显示帮助"
        print(help_msg)
        try:
            await self.send_log_to_frontend(help_msg)
        except Exception:
            pass  # 日志发送失败不影响主流程
        
        try:
            async for message in websocket:
                # 接收二进制数据（JPEG图片）
                if isinstance(message, bytes):
                    # 更新FPS统计
                    fps_result, total_frames = self.fps_monitor.update()
                    
                    # 保存图片
                    if self.image_manager.save_frame(message):
                        # 清理旧图片
                        self.image_manager.cleanup_old_images()
                    
                    # 如果前端已连接，转发图片数据给前端
                    if self.frontend_websocket is not None:
                        try:
                            await self.frontend_websocket.send(message)
                        except (websockets.exceptions.ConnectionClosed, Exception):
                            # 如果发送失败（连接已关闭或其他错误），则认为前端连接已失效
                            self.frontend_websocket = None
                    
                    # 如果达到统计时间，打印FPS
                    if fps_result is not None:
                        timestamp = datetime.now().strftime('%H:%M:%S')
                        log_msg = f"[{timestamp}] [Arduino] FPS: {fps_result:.2f} (总帧数: {total_frames})"
                        print(log_msg)
                        try:
                            await self.send_log_to_frontend(log_msg)
                        except Exception:
                            pass  # 日志发送失败不影响主流程
                else:
                    # 收到文本消息（ACK/STATUS）
                    message_str = message.decode('utf-8') if isinstance(message, bytes) else message
                    ts = datetime.now().strftime('%H:%M:%S')
                    log_msg = f"[{ts}] [Arduino] {message_str}"
                    print(log_msg)
                    try:
                        await self.send_log_to_frontend(log_msg)
                    except Exception:
                        pass  # 日志发送失败不影响主流程
                    
        except websockets.exceptions.ConnectionClosed:
            ts = datetime.now().strftime('%H:%M:%S')
            total_frames = self.fps_monitor.get_total_frames()
            log_msg1 = f"[{ts}] [Arduino] 断开连接: {client_address[0]}:{client_address[1]}"
            log_msg2 = f"[{ts}] [Arduino] 总共接收 {total_frames} 帧"
            print(log_msg1)
            print(log_msg2)
            try:
                await self.send_log_to_frontend(log_msg1)
                await self.send_log_to_frontend(log_msg2)
            except Exception:
                pass  # 日志发送失败不影响主流程
            self.arduino_websocket = None
        except Exception as e:
            ts = datetime.now().strftime('%H:%M:%S')
            log_msg = f"[{ts}] [Arduino] 处理连接时发生错误: {e}"
            print(log_msg)
            try:
                await self.send_log_to_frontend(log_msg)
            except Exception:
                pass  # 日志发送失败不影响主流程
            self.arduino_websocket = None
    
    async def handle_frontend(self, websocket):
        """处理前端开发者控制台连接（/dev）"""
        client_address = websocket.remote_address
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] [前端] 新连接: {client_address[0]}:{client_address[1]}")
        
        # 保存前端连接
        self.frontend_websocket = websocket
        
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
                if self.arduino_websocket is None:
                    error_msg = f"[{ts}] [服务器] 错误: Arduino未连接，无法转发命令"
                    print(error_msg)
                    try:
                        await self.send_log_to_frontend(error_msg)
                    except Exception:
                        pass  # 日志发送失败不影响主流程
                else:
                    try:
                        await self.arduino_websocket.send(message_str)
                        success_msg = f"[{ts}] [服务器] 已转发命令给Arduino: {message_str}"
                        print(success_msg)
                        try:
                            await self.send_log_to_frontend(success_msg)
                        except Exception:
                            pass  # 日志发送失败不影响主流程
                    except (websockets.exceptions.ConnectionClosed, Exception) as e:
                        error_msg = f"[{ts}] [服务器] 转发命令失败: {e}"
                        print(error_msg)
                        try:
                            await self.send_log_to_frontend(error_msg)
                        except Exception:
                            pass  # 日志发送失败不影响主流程
                        self.arduino_websocket = None
                    
        except websockets.exceptions.ConnectionClosed:
            ts = datetime.now().strftime('%H:%M:%S')
            print(f"[{ts}] [前端] 断开连接: {client_address[0]}:{client_address[1]}")
            self.frontend_websocket = None
        except Exception as e:
            ts = datetime.now().strftime('%H:%M:%S')
            print(f"[{ts}] [前端] 处理连接时发生错误: {e}")
            self.frontend_websocket = None
    
    async def handle_client(self, websocket):
        """根据路径路由到不同的处理函数"""
        # 在 websockets 15.0+ 中，路径通过 request.path 获取
        path = websocket.request.path
        if path == "/esp":
            await self.handle_arduino(websocket)
        elif path == "/dev":
            await self.handle_frontend(websocket)
        else:
            ts = datetime.now().strftime('%H:%M:%S')
            print(f"[{ts}] [服务器] 拒绝未知路径的连接: {path}")
            await websocket.close(code=1008, reason="Unknown endpoint")
    
    async def read_commands(self):
        """读取命令行输入并发送控制命令"""
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
                
                if self.arduino_websocket is None:
                    ts = datetime.now().strftime('%H:%M:%S')
                    print(f"[{ts}] [终端] 错误: Arduino未连接，无法发送命令")
                    continue
                
                # 发送命令到Arduino
                try:
                    await self.arduino_websocket.send(command)
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    print(f"[{timestamp}] [终端] 已发送命令: {command}")
                except Exception as e:
                    ts = datetime.now().strftime('%H:%M:%S')
                    print(f"[{ts}] [终端] 发送命令失败: {e}")
                    self.arduino_websocket = None
                    
            except EOFError:
                # 输入流关闭
                break
            except Exception as e:
                ts = datetime.now().strftime('%H:%M:%S')
                print(f"[{ts}] [终端] 读取命令时出错: {e}")
                await asyncio.sleep(0.1)
    
    async def start(self):
        """启动WebSocket服务器"""
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] [服务器] 启动WebSocket服务器...")
        print(f"[{ts}] [服务器] 监听地址: {self.host}:{self.port}")
        print(f"[{ts}] [服务器] 图片保存路径: {self.image_manager.images_dir}")
        print(f"[{ts}] [服务器] 最多保存图片数: {self.image_manager.max_images}")
        print(f"[{ts}] [服务器] 支持的endpoint:")
        print(f"[{ts}] [服务器]   /esp - Arduino摄像头客户端")
        print(f"[{ts}] [服务器]   /dev - 开发者前端控制台")
        print(f"[{ts}] [服务器] 等待客户端连接...")
        print("-" * 60)
        
        # 启动命令行输入任务
        command_task = asyncio.create_task(self.read_commands())
        
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()  # 永久运行


async def main():
    """主函数：创建并启动WebSocket服务器"""
    server = WebSocketServer()
    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"\n[{ts}] [服务器] 服务器已停止")
