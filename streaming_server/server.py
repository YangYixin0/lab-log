"""WebSocket服务器：接收Android App的MP4视频分段并实时处理（动态上下文版本）"""

import argparse
import asyncio
import base64
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

import websockets

# 导入实时处理相关模块
from streaming_server.monitoring import MonitoringLogger
from storage.models import VideoSegment
from storage.seekdb_client import SeekDBClient
from utils.segment_time_parser import parse_segment_times

# 动态上下文相关模块
from context.appearance_cache import AppearanceCache
from context.event_context import EventContext
from video_processing.qwen3_vl_processor import Qwen3VLProcessor
from log_writer.writer import SimpleLogWriter

RECORDINGS_ROOT = Path("recordings")
RECORDINGS_ROOT.mkdir(parents=True, exist_ok=True)

# 调试日志目录
DEBUG_LOG_DIR = Path("logs_debug")
DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 跟踪当前已连接的客户端及其录制会话
CONNECTED_CLIENTS = set()
RECORDING_SESSIONS: Dict[websockets.WebSocketServerProtocol, "RecordingSession"] = {}

# 环境变量配置
def get_config(key: str, default, type_func: type = str):
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
DYNAMIC_CONTEXT_ENABLED = get_config('DYNAMIC_CONTEXT_ENABLED', True, bool)
MAX_RECENT_EVENTS = get_config('MAX_RECENT_EVENTS', 20, int)
APPEARANCE_DUMP_INTERVAL = get_config('APPEARANCE_DUMP_INTERVAL', 5, int)  # 每 N 个分段 dump 一次


class RecordingSession:
    """
    针对单个客户端的一次录制会话：
    - 在 recordings/ 下为每个会话创建独立目录
    - 接收Android端封装的MP4分段
    - 如果启用实时处理，将MP4分段加入处理队列
    - 支持动态上下文（人物外貌缓存、事件上下文）
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
        
        # 动态上下文相关
        self.appearance_cache: Optional[AppearanceCache] = None
        self.event_context: Optional[EventContext] = None
        self.db_client: Optional[SeekDBClient] = None
        self.log_writer: Optional[SimpleLogWriter] = None
        self.video_processor: Optional[Qwen3VLProcessor] = None
        
        # 统计字段
        self.processed_segments_count = 0
        self.total_temp_size_mb = 0.0
        self.processing_stats: List[Dict] = []
        
        # 监控日志记录器
        self.monitor = MonitoringLogger() if self.enable_realtime_processing else None
        
        # 分段计数器（用于统计）
        self.segment_count = 0
        
        # 外貌缓存文件路径
        self.appearance_cache_path = DEBUG_LOG_DIR / "appearances_today.json"
    
    def init_dynamic_context(self):
        """初始化动态上下文组件"""
        if not DYNAMIC_CONTEXT_ENABLED:
            return
        
        try:
            # 创建数据库客户端
            self.db_client = SeekDBClient()
            
            # 创建人物外貌缓存（尝试从文件加载）
            self.appearance_cache = AppearanceCache()
            if self.appearance_cache_path.exists():
                loaded = self.appearance_cache.load_from_file(str(self.appearance_cache_path))
                if loaded:
                    print(f"[Context]: 加载外貌缓存成功，共 {self.appearance_cache.get_record_count()} 条记录")
            
            # 创建事件上下文
            self.event_context = EventContext(self.db_client)
            
            # 创建日志写入器（不加密）
            self.log_writer = SimpleLogWriter(self.db_client)
            
            # 创建视频处理器（使用动态上下文）
            self.video_processor = Qwen3VLProcessor(
                appearance_cache=self.appearance_cache,
                event_context=self.event_context,
                max_recent_events=MAX_RECENT_EVENTS
            )
            
            print(f"[Context]: 动态上下文初始化成功")
        except Exception as e:
            print(f"[Context]: 动态上下文初始化失败: {e}")
            import traceback
            traceback.print_exc()
            # 回退到非动态上下文模式
            self._cleanup_context()
    
    def _cleanup_context(self):
        """清理动态上下文资源"""
        if self.event_context:
            self.event_context.close()
            self.event_context = None
        if self.db_client:
            self.db_client.close()
            self.db_client = None
        self.appearance_cache = None
        self.log_writer = None
        self.video_processor = None
    
    def dump_appearance_cache(self):
        """保存外貌缓存到文件"""
        if self.appearance_cache:
            try:
                self.appearance_cache.dump_to_file(str(self.appearance_cache_path))
                print(f"[Context]: 外貌缓存已保存，共 {self.appearance_cache.get_record_count()} 条记录")
            except Exception as e:
                print(f"[Context]: 保存外貌缓存失败: {e}")
    
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
        start_time, end_time = parse_segment_times(segment_id, REALTIME_TARGET_SEGMENT_DURATION)
        
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
        """关闭会话"""
        # 保存外貌缓存
        self.dump_appearance_cache()
        # 清理动态上下文资源
        self._cleanup_context()

    async def finalize(self) -> Optional[Path]:
        """
        结束会话：
        - 如果启用实时处理，等待处理队列完成
        - 保存外貌缓存
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
        
        # 保存外貌缓存
        self.dump_appearance_cache()
        
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


async def process_segment_queue_dynamic(session: RecordingSession):
    """
    后台串行处理分段队列（动态上下文版本）
    
    使用动态上下文进行视频理解，维护人物外貌缓存
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
                
                loop = asyncio.get_event_loop()
                
                # 获取最近事件和最大事件编号
                recent_events = []
                max_event_id = 0
                if session.event_context:
                    recent_events = session.event_context.get_recent_events(MAX_RECENT_EVENTS)
                    max_event_id = session.event_context.get_max_event_id_number()
                
                # 视频理解（使用动态上下文）
                video_process_start = time.time()
                
                if session.video_processor and session.appearance_cache:
                    # 使用动态上下文处理
                    result = await loop.run_in_executor(
                        None,
                        session.video_processor.process_segment_with_context,
                        segment,
                        session.appearance_cache,
                        recent_events,
                        max_event_id
                    )
                    
                    # 应用外貌更新
                    await loop.run_in_executor(
                        None,
                        session.video_processor._apply_appearance_updates,
                        result.appearance_updates
                    )
                    
                    events = result.events
                    appearance_update_count = len(result.appearance_updates)
                else:
                    # 回退到旧模式
                    from orchestration.pipeline import VideoLogPipeline
                    pipeline = VideoLogPipeline(enable_indexing=False)
                    result = await loop.run_in_executor(
                        None,
                        pipeline.video_processor.process_segment,
                        segment
                    )
                    events = result.events
                    appearance_update_count = 0
                
                video_process_time = time.time() - video_process_start
                
                # 写入日志
                if session.log_writer:
                    for event in events:
                        session.log_writer.write_event_log(event)
                
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
                    'events_count': len(events),
                    'appearance_updates': appearance_update_count,
                    'mp4_size_mb': mp4_size_mb,
                    'total_temp_size_mb': total_size_mb,
                    'processed_segments_count': session.processed_segments_count
                }
                session.processing_stats.append(stats)
                
                # 监控记录（仅写入文件，不打印）
                if session.monitor:
                    session.monitor.log_segment_processing(stats)

                # 精简单行日志
                appearance_info = ""
                if session.appearance_cache:
                    appearance_info = f", 外貌更新={appearance_update_count}, 外貌总数={session.appearance_cache.get_record_count()}"
                
                print(
                    "[Realtime] 分段 {sid}: 事件数={ev}{app}, 时长={dur:.1f}s, 处理={proc:.2f}s, "
                    "MP4={size:.2f}MB, 已处理={cnt}, 队列={q}".format(
                        sid=segment_info['segment_id'],
                        ev=len(events),
                        app=appearance_info,
                        dur=segment_duration,
                        proc=processing_time,
                        size=mp4_size_mb,
                        cnt=session.processed_segments_count,
                        q=queue_length,
                    )
                )
                
                # 周期性保存外貌缓存
                if session.processed_segments_count % APPEARANCE_DUMP_INTERVAL == 0:
                    session.dump_appearance_cache()
                
            except Exception as e:
                print(f"[Realtime] 处理分段失败: {e}")
                import traceback
                traceback.print_exc()
            
            session.processing_queue.task_done()
            
        except asyncio.TimeoutError:
            # 继续等待，可能还有分段会加入队列
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
        
        # 初始化动态上下文
        if DYNAMIC_CONTEXT_ENABLED:
            session.init_dynamic_context()
        
        # 启动后台处理任务
        session.processing_task = asyncio.create_task(
            process_segment_queue_dynamic(session)
        )
        
        context_info = "（动态上下文）" if session.appearance_cache else ""
        print(f"[Info]: Started recording session with realtime processing{context_info} at {session.session_dir}")
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
    
    # 清理会话资源
    session.close()


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
                            loop = asyncio.get_event_loop()
                            mp4_data = await loop.run_in_executor(
                                None, 
                                base64.b64decode, 
                                base64_data
                            )
                            decode_time = time.time() - decode_start
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
                    print(f"[Warning]: Failed to parse JSON message from {client_id}: {e}")
                    pass
            else:
                # 二进制消息：不再处理H264帧，忽略
                print(f"[Warning]: Received binary message from {client_id}, but binary H264 frame handling is disabled. Ignoring.")

    except websockets.exceptions.ConnectionClosed as e:
        print(f"[Connection]: Client {client_id} disconnected: code={e.code}, reason={e.reason}")
        if e.code == 1006:
            print(f"[Warning]: 连接异常关闭 (1006)，可能是网络中断或超时")
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
    新客户端连接入口
    """
    CONNECTED_CLIENTS.add(websocket)
    client_id = f"{websocket.remote_address[0]}_{websocket.remote_address[1]}"
    path = websocket.request.path
    print(
        f"[Connection]: New client {client_id} connected from {path}. Total clients: {len(CONNECTED_CLIENTS)}"
    )
    try:
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
    """
    if CONNECTED_CLIENTS:
        print(f"[Broadcast]: Sending to {len(CONNECTED_CLIENTS)} client(s): {message}")
        results = await asyncio.gather(
            *[client.send(message) for client in CONNECTED_CLIENTS],
            return_exceptions=True
        )
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
                aspect_width, aspect_height = 4, 3
                bitrate_mb = 1.0
                fps = 10
                include_aspect_ratio = len(parts) > 1

                if include_aspect_ratio:
                    try:
                        aspect_width, aspect_height = map(int, parts[1].split(":"))
                        if aspect_width <= 0 or aspect_height <= 0:
                            raise ValueError("Aspect ratio must be positive")
                    except (ValueError, IndexError):
                        print("[Error]: Invalid aspect ratio format. Using default 4:3.")
                        aspect_width, aspect_height = 4, 3

                if len(parts) > 2:
                    try:
                        bitrate_mb = float(parts[2])
                        if bitrate_mb <= 0:
                            raise ValueError("Bitrate must be positive")
                    except ValueError:
                        print("[Error]: Invalid bitrate. Using default 1 MB.")
                        bitrate_mb = 1.0

                if len(parts) > 3:
                    try:
                        fps = int(parts[3])
                        if fps < 0:
                            fps = 10
                    except ValueError:
                        print("[Error]: Invalid fps. Using 10 FPS.")
                        fps = 10

                payload = {
                    "format": "h264",
                    "bitrate": int(bitrate_mb) if isinstance(bitrate_mb, float) and bitrate_mb.is_integer() else bitrate_mb,
                    "fps": fps,
                    "segmentDuration": REALTIME_TARGET_SEGMENT_DURATION,
                }
                if include_aspect_ratio:
                    payload["aspectRatio"] = {
                        "width": aspect_width,
                        "height": aspect_height,
                    }

                message = json.dumps({
                    "command": "start_capture",
                    "payload": payload,
                })
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
    server_task = websockets.serve(
        connection_handler, 
        host, 
        port,
        ping_interval=20,
        ping_timeout=10,
        close_timeout=10,
        max_size=10 * 1024 * 1024
    )
    async with server_task:
        print(f"WebSocket server started at ws://{host}:{port}")
        print("You can now connect your Android Camera App.")
        if REALTIME_PROCESSING_ENABLED:
            print(f"[Info]: Realtime processing enabled (target segment duration: {REALTIME_TARGET_SEGMENT_DURATION}s)")
        if DYNAMIC_CONTEXT_ENABLED:
            print(f"[Info]: Dynamic context enabled (max recent events: {MAX_RECENT_EVENTS})")
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
