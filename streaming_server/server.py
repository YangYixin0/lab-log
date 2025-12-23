"""WebSocket服务器：接收Android App的MP4视频分段并实时处理"""

import argparse
import asyncio
import base64
import json
import os
import struct
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

import websockets

# 导入实时处理相关模块
from streaming_server.monitoring import MonitoringLogger
from orchestration.pipeline import VideoLogPipeline
from storage.models import VideoSegment
RECORDINGS_ROOT = Path("recordings")
RECORDINGS_ROOT.mkdir(parents=True, exist_ok=True)

# 跟踪当前已连接的客户端及其录制会话
CONNECTED_CLIENTS = set()
RECORDING_SESSIONS: Dict[websockets.WebSocketServerProtocol, "RecordingSession"] = {}

# 环境变量配置
def get_config(key: str, default: any, type_func: type = str):
    """从环境变量读取配置"""
    value = os.getenv(key)
    if value is None:
        return default
    if type_func == bool:
        return value.lower() in ('true', '1', 'yes', 'on')
    return type_func(value)

REALTIME_PROCESSING_ENABLED = get_config('REALTIME_PROCESSING_ENABLED', True, bool)
REALTIME_TARGET_SEGMENT_DURATION = get_config('REALTIME_TARGET_SEGMENT_DURATION', 60.0, float)
REALTIME_QUEUE_ALERT_THRESHOLD = get_config('REALTIME_QUEUE_ALERT_THRESHOLD', 10, int)
REALTIME_CLEANUP_H264 = get_config('REALTIME_CLEANUP_H264', True, bool)


class RecordingSession:
    """
    针对单个客户端的一次录制会话：
    - 在 recordings/ 下为每个会话创建独立目录
    - 接收Android端封装的MP4分段
    - 如果启用实时处理，将MP4分段加入处理队列
    """
    def __init__(self, client_id: str, enable_realtime_processing: bool = False):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.client_id = client_id
        self.session_dir = RECORDINGS_ROOT / f"{client_id}_{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # 实时处理相关
        self.enable_realtime_processing = enable_realtime_processing and REALTIME_PROCESSING_ENABLED
        
        # 处理队列（异步处理）
        self.processing_queue: Optional[asyncio.Queue] = None
        self.processing_task: Optional[asyncio.Task] = None
        
        # 统计字段
        self.processed_segments_count = 0
        self.total_temp_size_mb = 0.0
        self.processing_stats: List[Dict] = []
        
        # 监控日志记录器
        self.monitor = MonitoringLogger() if self.enable_realtime_processing else None
        
        # 分段计数器（用于统计）
        self.segment_count = 0
    
    def handle_mp4_segment(self, segment_id: str, mp4_data: bytes, qr_results: Optional[List] = None):
        """
        处理接收到的MP4分段：
        - 保存MP4文件到会话目录
        - 生成时间戳
        - 加入处理队列（如果启用实时处理）
        """
        qr_results = qr_results or []
        # 保存MP4文件（使用segment_id作为文件名，已包含时间戳和序号）
        segment_path = self.session_dir / f"{segment_id}.mp4"
        segment_path.write_bytes(mp4_data)
        # 保存二维码识别结果
        qr_path = self.session_dir / f"{segment_id}_qr.json"
        try:
            qr_path.write_text(json.dumps(qr_results, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[Warning]: Failed to save QR results for {segment_id}: {e}")
        
        # 生成时间戳（从segment_id中提取，格式：YYYYMMDD_HHMMSS_XX）
        # 如果无法解析，使用当前时间
        try:
            # segment_id格式：20251221_195713_00
            parts = segment_id.split('_')
            if len(parts) >= 2:
                date_str = parts[0]  # 20251221
                time_str = parts[1]   # 195713
                timestamp_str = f"{date_str}_{time_str}"
                # 解析为datetime
                segment_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                start_time = segment_time.timestamp()
                # 估算结束时间（假设分段时长为target_segment_duration）
                end_time = start_time + REALTIME_TARGET_SEGMENT_DURATION
            else:
                # 无法解析，使用当前时间
                current_time = time.time()
                start_time = current_time
                end_time = current_time + REALTIME_TARGET_SEGMENT_DURATION
        except Exception as e:
            print(f"[Warning]: Failed to parse timestamp from segment_id {segment_id}: {e}")
            current_time = time.time()
            start_time = current_time
            end_time = current_time + REALTIME_TARGET_SEGMENT_DURATION
        
        self.segment_count += 1
        print(f"[Info]: Saved MP4 segment {segment_id} ({len(mp4_data)} bytes) to {segment_path}")
        
        # 如果启用实时处理，加入处理队列
            if self.enable_realtime_processing and self.processing_queue:
            segment_info = {
                'segment_id': segment_id,
                'segment_path': str(segment_path),
                'start_time': start_time,
                    'end_time': end_time,
                    'mp4_size_mb': len(mp4_data) / (1024 * 1024),
                    'qr_results': qr_results
            }
            self.processing_queue.put_nowait(segment_info)
    
    def close(self):
        """关闭会话（不再需要关闭文件）"""
        pass

    async def finalize(self) -> Optional[Path]:
        """
        结束会话：
        - 如果启用实时处理，等待处理队列完成
        """
        # 如果启用实时处理，等待处理队列完成
        if self.enable_realtime_processing and self.processing_task:
            print(f"[Info]: Waiting for processing queue to complete...")
            try:
                # 等待处理任务完成，最多等待30秒
                await asyncio.wait_for(self.processing_task, timeout=30.0)
            except asyncio.TimeoutError:
                print(f"[Warning]: Processing task timeout after 30 seconds")
            except Exception as e:
                print(f"[Error]: Error waiting for processing task: {e}")
        
        print(f"[Info]: Recording session finalized. Processed {self.segment_count} segments.")
        return None


def extract_first_frame_from_mp4(mp4_path: Path, output_path: Path) -> Optional[Path]:
    """
    从 MP4 文件中提取第一帧并保存为 JPEG 图片。
    视频已在 Android 端旋转完成，无需后端再旋转。
    """
    if not mp4_path.exists():
        print(f"[Warning]: MP4 file not found: {mp4_path}; skip thumbnail extraction.")
        return None

    cmd = [
        os.environ.get("FFMPEG_BIN", "ffmpeg"),
        "-y",
        "-i", str(mp4_path),
        "-vframes", "1",
        "-q:v", "2",  # 高质量 JPEG (2-31, 2 是最高质量)
        str(output_path),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[Warning]: ffmpeg failed to extract thumbnail from {mp4_path}")
        print(result.stderr.strip())
        return None

    return output_path


async def process_segment_queue(session: RecordingSession, pipeline: VideoLogPipeline):
    """
    后台串行处理分段队列（不阻塞接收）
    
    注意：这个函数会一直运行直到会话结束（raw_file关闭）或任务被取消
    """
    while True:
        try:
            # 从队列中获取分段（串行，一次只处理一个）
            segment_info = await asyncio.wait_for(
                session.processing_queue.get(), 
                timeout=1.0
            )
            
            # 记录处理开始时间
            processing_start_time = time.time()
            queue_length = session.processing_queue.qsize()
            
            # 处理分段
            try:
                segment = VideoSegment(
                    segment_id=segment_info['segment_id'],
                    video_path=segment_info['segment_path'],
                    start_time=segment_info['start_time'],
                    end_time=segment_info['end_time'],
                    qr_results=segment_info.get('qr_results', [])
                )
                
                # 视频理解（可能较慢，但不阻塞接收）
                # 将视频理解和缩略图提取放到后台线程，避免阻塞事件循环
                loop = asyncio.get_event_loop()
                
                # 视频理解（同步调用，但已在后台任务中）
                video_process_start = time.time()
                result = await loop.run_in_executor(
                    None,
                    pipeline.video_processor.process_segment,
                    segment
                )
                video_process_time = time.time() - video_process_start
                
                # 写入日志
                for event in result.events:
                    pipeline.log_writer.write_event_log(event)
                
                # 提取缩略图（从MP4的第一帧）
                segment_mp4_path = Path(segment_info['segment_path'])
                thumbnail_path = segment_mp4_path.parent / f"{segment_info['segment_id']}_thumbnail.jpg"
                thumbnail_start = time.time()
                await loop.run_in_executor(
                    None,
                    extract_first_frame_from_mp4,
                    segment_mp4_path,
                    thumbnail_path
                )
                thumbnail_time = time.time() - thumbnail_start
                
                # 计算处理用时
                processing_time = time.time() - processing_start_time
                segment_duration = segment_info['end_time'] - segment_info['start_time']
                
                # 获取MP4文件大小
                mp4_size_mb = segment_info['mp4_size_mb']
                
                # 更新统计
                session.processed_segments_count += 1
                session.total_temp_size_mb += mp4_size_mb
                
                # 计算总临时文件大小
                total_size_mb = sum(
                    f.stat().st_size / (1024 * 1024)
                    for f in session.session_dir.glob("*.mp4")
                )
                
                # 构建统计信息
                stats = {
                    'segment_id': segment_info['segment_id'],
                    'segment_duration': segment_duration,
                    'processing_time': processing_time,
                    'queue_length': queue_length,
                    'events_count': len(result.events),
                    'mp4_size_mb': mp4_size_mb,
                    'total_temp_size_mb': total_size_mb,
                    'processed_segments_count': session.processed_segments_count
                }
                session.processing_stats.append(stats)
                
                # 监控记录（仅写入文件，不打印）
                if session.monitor:
                    session.monitor.log_segment_processing(stats)

                # 精简单行日志
                print(
                    "[Realtime] 分段 {sid}: 包含事件数={ev}, 时长={dur:.1f}s, 处理={proc:.2f}s, "
                    "MP4={size:.2f}MB, 临时文件={tmp:.2f}MB, 已处理分段数={cnt}, 队列={q}".format(
                        sid=segment_info['segment_id'],
                        ev=len(result.events),
                        dur=segment_duration,
                        proc=processing_time,
                        size=mp4_size_mb,
                        tmp=total_size_mb,
                        cnt=session.processed_segments_count,
                        q=queue_length,
                    )
                )
                
            except Exception as e:
                print(f"[Realtime] 处理分段失败: {e}")
            
            session.processing_queue.task_done()
            
        except asyncio.TimeoutError:
            # 继续等待，可能还有分段会加入队列
            # 不打印日志，避免日志过多
            continue
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Realtime] 处理队列异常: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(1)


async def start_recording(websocket, client_id: str):
    """
    开始一个新的录制会话。
    视频已在 Android 端旋转完成，无需记录 rotation。
    """
    if websocket in RECORDING_SESSIONS:
        await finalize_recording(websocket, client_id)
    
    # 启用实时处理
    session = RecordingSession(client_id, enable_realtime_processing=True)
    RECORDING_SESSIONS[websocket] = session
    
    # 如果启用实时处理，创建处理队列和任务
    if session.enable_realtime_processing:
        session.processing_queue = asyncio.Queue()
        # 创建处理流程（共享实例，避免重复创建）
        # 索引不再由视频处理触发，统一由独立脚本处理
        pipeline = VideoLogPipeline(enable_indexing=False)
        # 启动后台处理任务
        session.processing_task = asyncio.create_task(
            process_segment_queue(session, pipeline)
        )
        print(f"[Info]: Started recording session with realtime processing at {session.session_dir}")
    else:
        print(f"[Info]: Started recording session at {session.session_dir}")


async def finalize_recording(websocket, client_id: str):
    session = RECORDING_SESSIONS.pop(websocket, None)
    if not session:
        return
    
    # 如果启用实时处理，等待处理队列完成
    if session.enable_realtime_processing and session.processing_queue:
        # 等待队列处理完成
        try:
            # 等待队列为空（最多等待30秒，避免无限等待）
            max_wait_time = 30.0
            wait_start = time.time()
            while not session.processing_queue.empty():
                if time.time() - wait_start > max_wait_time:
                    print(f"[Warning]: 等待处理队列超时（{max_wait_time}秒），强制继续")
                    break
                await asyncio.sleep(0.1)
            
            # 等待所有任务完成（最多等待30秒）
            wait_start = time.time()
            while session.processing_queue.qsize() > 0 or (session.processing_task and not session.processing_task.done()):
                if time.time() - wait_start > max_wait_time:
                    print(f"[Warning]: 等待处理任务完成超时（{max_wait_time}秒），强制继续")
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[Warning]: 等待处理队列完成时出错: {e}")
            import traceback
            traceback.print_exc()
        
        # 取消处理任务
        if session.processing_task and not session.processing_task.done():
            session.processing_task.cancel()
            try:
                await asyncio.wait_for(session.processing_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
    
    mp4_path = await session.finalize()
    if mp4_path:
        print(f"[Info]: MP4 saved to {mp4_path}")
    else:
        print("[Info]: Recording session finalized.")


# This handler manages receiving messages from a client
async def consumer_handler(websocket):
    """
    处理来自单个客户端的所有消息：
    - 文本消息：视为 JSON 状态（ClientStatus），用于开始 / 结束录制
    - 二进制消息：视为一帧 H.264 数据（带自定义帧头），写入对应会话
    """
    client_id = f"{websocket.remote_address[0]}_{websocket.remote_address[1]}"
    
    try:
        message_count = 0
        # 确保WebSocket连接支持ping/pong
        # websockets库的ping_interval和ping_timeout在serve()中设置，会自动应用到所有连接
        async for message in websocket:
            message_count += 1
            receive_time = time.time()
            if isinstance(message, str):
                # 文本：来自 App 的 JSON 消息（状态或MP4分段）
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "mp4_segment":
                        # MP4分段消息
                        session = RECORDING_SESSIONS.get(websocket)
                        if not session:
                            print(f"[Warning]: Received MP4 segment from {client_id} without active session.")
                            continue
                        
                        segment_id = data.get("segment_id")
                        base64_data = data.get("data")
                        qr_results = data.get("qr_results", [])
                        segment_size = data.get("size", 0)
                        
                        if not segment_id or not base64_data:
                            print(f"[Error]: Invalid MP4 segment message from {client_id}")
                            continue
                        
                        # Base64解码MP4数据（在后台线程执行，避免阻塞消息接收）
                        try:
                            decode_start = time.time()
                            # 将Base64解码放到后台线程，避免阻塞WebSocket消息接收循环
                            loop = asyncio.get_event_loop()
                            mp4_data = await loop.run_in_executor(
                                None, 
                                base64.b64decode, 
                                base64_data
                            )
                            decode_time = time.time() - decode_start
                            # handle_mp4_segment是同步的，也放到后台线程执行
                            await loop.run_in_executor(
                                None,
                                session.handle_mp4_segment,
                                segment_id,
                                mp4_data,
                                qr_results
                            )
                        except Exception as e:
                            print(f"[Error]: Failed to decode/handle MP4 segment from {client_id}: {e}")
                            import traceback
                            traceback.print_exc()
                            continue
                        
                        # 监控队列长度
                        if session.enable_realtime_processing and session.processing_queue:
                            queue_length = session.processing_queue.qsize()
                            if queue_length >= REALTIME_QUEUE_ALERT_THRESHOLD and session.monitor:
                                session.monitor.print_queue_warning(queue_length, REALTIME_QUEUE_ALERT_THRESHOLD)
                    else:
                        # 状态消息
                        status = data.get("status")
                        if status == "capture_started":
                            await start_recording(websocket, client_id)
                        elif status == "capture_stopped":
                            await finalize_recording(websocket, client_id)
                except (json.JSONDecodeError, TypeError) as e:
                    # 不是我们关心的 JSON，忽略
                    print(f"[Warning]: Failed to parse JSON message from {client_id}: {e}")
                    pass
            else:
                # 二进制消息：不再处理H264帧，忽略
                print(f"[Warning]: Received binary message from {client_id}, but binary H264 frame handling is disabled. Ignoring.")

    except websockets.exceptions.ConnectionClosed as e:
        print(f"[Connection]: Client {client_id} disconnected: code={e.code}, reason={e.reason}")
        if e.code == 1006:
            print(f"[Warning]: 连接异常关闭 (1006)，可能是网络中断或超时")
            # 检查是否有未处理的分段
            session = RECORDING_SESSIONS.get(websocket)
            if session and session.enable_realtime_processing and session.processing_queue:
                queue_size = session.processing_queue.qsize()
                if queue_size > 0:
                    print(f"[Warning]: 连接断开时，处理队列中还有 {queue_size} 个分段未处理")
        elif e.code == 1000:
            print(f"[Info]: 连接正常关闭 (1000)")
        else:
            print(f"[Info]: 连接关闭，代码={e.code}")
    except Exception as e:
        print(f"[Error]: 处理客户端 {client_id} 时发生异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await finalize_recording(websocket, client_id)
        print(f"[Info]: Recording session for {client_id} closed.")


# This handler manages the overall connection for a client
async def connection_handler(websocket):
    """
    新客户端连接入口：
    - 记录客户端 ID 与请求路径
    - 将连接加入 CONNECTED_CLIENTS，方便广播控制命令
    - 委托给 consumer_handler 处理具体收发逻辑
    """
    CONNECTED_CLIENTS.add(websocket)
    client_id = f"{websocket.remote_address[0]}_{websocket.remote_address[1]}"
    path = websocket.request.path
    print(
        f"[Connection]: New client {client_id} connected from {path}. Total clients: {len(CONNECTED_CLIENTS)}"
    )
    try:
        # 设置WebSocket的ping/pong机制，确保连接保持活跃
        # websockets库会自动处理ping/pong，但我们需要确保连接对象支持
        await consumer_handler(websocket)
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[Connection]: Connection closed in connection_handler: code={e.code}, reason={e.reason}")
        raise
    finally:
        CONNECTED_CLIENTS.remove(websocket)
        print(
            f"[Connection]: Client {client_id} removed. Total clients: {len(CONNECTED_CLIENTS)}"
        )


# This function broadcasts messages to all connected clients
async def broadcast(message):
    """
    将控制命令广播给所有已连接客户端。
    当前主要用于从终端向所有 Android App 发送 start/stop_capture 指令。
    """
    if CONNECTED_CLIENTS:
        print(f"[Broadcast]: Sending to {len(CONNECTED_CLIENTS)} client(s): {message}")
        # 使用 gather 而不是 wait，以便正确处理断开连接的客户端
        results = await asyncio.gather(
            *[client.send(message) for client in CONNECTED_CLIENTS],
            return_exceptions=True
        )
        # 记录发送失败的客户端
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[Broadcast]: Failed to send to a client: {result}")
    else:
        print("[Broadcast]: No clients connected to send message.")


# This function reads commands from the server's terminal
async def terminal_input_handler():
    """
    终端交互：
    - 支持在服务器命令行输入 start/stop 命令
    - 将命令转换为 JSON 下发到所有已连接客户端
    - start 命令可携带分辨率 / 码率 / 目标 FPS
    """
    loop = asyncio.get_running_loop()
    while True:
        try:
            command_str = await loop.run_in_executor(
                None,
                lambda: input(
                    "\nEnter command ('start [w]:[h] [bitrate_mb] [fps]' or 'stop'): \n"
                    "  Example: 'start 4:3 4 10' for 4:3 aspect ratio, 4 MB bitrate, 10 fps\n> "
                ),
            )
            parts = command_str.lower().split()
            if not parts:
                continue
            command = parts[0]

            if command == "start":
                # 默认参数：码率和 FPS；宽高比是否下发由命令是否携带参数决定
                aspect_width, aspect_height = 4, 3  # 默认宽高比，仅在带参数时才下发
                bitrate_mb = 1.0  # 默认 1 MB（会在客户端转换为 bps）
                fps = 10  # 默认 10 FPS

                # 是否由服务器显式指定宽高比：
                # - 纯 "start"           -> 不下发 aspectRatio 字段，交由客户端使用当前 UI 选择的宽高比
                # - "start 4:3 ..." 等   -> 在 payload 中下发 aspectRatio，强制客户端使用该宽高比
                include_aspect_ratio = len(parts) > 1

                if include_aspect_ratio:
                    try:
                        aspect_width, aspect_height = map(int, parts[1].split(":"))
                        if aspect_width <= 0 or aspect_height <= 0:
                            raise ValueError("Aspect ratio must be positive")
                    except (ValueError, IndexError):
                        print(
                            "[Error]: Invalid aspect ratio format. Use 'WIDTH:HEIGHT', e.g., '4:3' or '16:9'. Using default 4:3."
                        )
                        aspect_width, aspect_height = 4, 3

                if len(parts) > 2:
                    try:
                        bitrate_mb = float(parts[2])
                        if bitrate_mb <= 0:
                            raise ValueError("Bitrate must be positive")
                    except ValueError:
                        print(
                            "[Error]: Invalid bitrate. Expecting positive number (MB). Using default 1 MB."
                        )
                        bitrate_mb = 1.0

                if len(parts) > 3:
                    try:
                        fps = int(parts[3])
                        if fps < 0:
                            fps = 10  # Default to 10 FPS if invalid
                    except ValueError:
                        print(
                            "[Error]: Invalid fps. Expecting integer. Using 10 FPS."
                        )
                        fps = 10

                payload = {
                    "format": "h264",
                    "bitrate": int(bitrate_mb) if isinstance(bitrate_mb, float) and bitrate_mb.is_integer() else bitrate_mb,  # In MB, client will convert to bps
                    "fps": fps,
                    "segmentDuration": REALTIME_TARGET_SEGMENT_DURATION,  # 分段时长（秒）
                }
                if include_aspect_ratio:
                    payload["aspectRatio"] = {
                        "width": aspect_width,
                        "height": aspect_height,
                    }

                message = json.dumps(
                    {
                        "command": "start_capture",
                        "payload": payload,
                    }
                )
                await broadcast(message)

            elif command == "stop":
                message = json.dumps({"command": "stop_capture"})
                await broadcast(message)
            else:
                print(f"[Error]: Unknown command '{command}'. Use 'start' or 'stop'.")

        except (KeyboardInterrupt, asyncio.CancelledError):
            break
        except Exception as e:
            print(f"[Error] in terminal handler: {e}")
            continue


# The main function to start the server and the terminal handler
async def main(host: str = "0.0.0.0", port: int = 50002):
    # 设置WebSocket ping_interval和ping_timeout，保持连接活跃
    # ping_interval: 每20秒发送一次ping
    # ping_timeout: 等待pong响应的超时时间（10秒）
    # Android 端每段 MP4 约 0.5~1.5 MB，Base64 后会膨胀约 1.33 倍。
    # websockets 默认 max_size=1MB，会在第二段（~1.7MB）时触发 1009/1006 断开。
    # 将 max_size 提高到 10MB 以容纳 15s 分段，避免首段后即被服务器强制断开。
    server_task = websockets.serve(
        connection_handler, 
        host, 
        port,
        ping_interval=20,  # 每20秒发送一次ping
        ping_timeout=10,   # 等待pong响应的超时时间
        close_timeout=10,  # 关闭连接的超时时间
        max_size=10 * 1024 * 1024  # 允许更大的 Base64 MP4 消息
    )
    async with server_task:
        print(f"WebSocket server started at ws://{host}:{port}")
        print("You can now connect your Android Camera App.")
        if REALTIME_PROCESSING_ENABLED:
            print(f"[Info]: Realtime processing enabled (target segment duration: {REALTIME_TARGET_SEGMENT_DURATION}s)")
        terminal_task = asyncio.create_task(terminal_input_handler())
        await asyncio.gather(terminal_task)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=50002)
    args = parser.parse_args()

    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        print("\nServer shutting down.")

