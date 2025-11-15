#!/usr/bin/env python3
"""
WebSocket服务器，接收ESP32发送的随机数并打印到终端
"""
import asyncio
import websockets
import json
from datetime import datetime

# 服务器配置
HOST = "0.0.0.0"
PORT = 50001

async def handle_client(websocket):
    """处理客户端连接"""
    client_address = websocket.remote_address
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 新客户端连接: {client_address[0]}:{client_address[1]}")
    
    try:
        async for message in websocket:
            # 接收消息
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            try:
                # 尝试解析为JSON（如果将来需要扩展）
                data = json.loads(message)
                print(f"[{timestamp}] 客户端 {client_address[0]}:{client_address[1]} 发送: {data}")
            except json.JSONDecodeError:
                # 如果不是JSON，直接打印原始消息
                print(f"[{timestamp}] 客户端 {client_address[0]}:{client_address[1]} 发送随机数: {message}")
                
    except websockets.exceptions.ConnectionClosed:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 客户端 {client_address[0]}:{client_address[1]} 断开连接")
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 处理客户端 {client_address[0]}:{client_address[1]} 时发生错误: {e}")

async def main():
    """启动WebSocket服务器"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 启动WebSocket服务器...")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 监听地址: {HOST}:{PORT}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 等待客户端连接...")
    print("-" * 60)
    
    async with websockets.serve(handle_client, HOST, PORT):
        await asyncio.Future()  # 永久运行

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 服务器已停止")

