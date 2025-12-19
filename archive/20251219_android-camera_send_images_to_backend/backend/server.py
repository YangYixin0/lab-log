import argparse
import asyncio
import json
import os
import struct
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import websockets

# 自定义帧头格式（与 Android 端严格对应）：
# - Q: uint64  设备时间戳（毫秒）
# - I: uint32  帧序号（循环递增）
# - I: uint32  后续 H.264 负载长度（字节数）
FRAME_HEADER_FORMAT = ">QII"
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)
RECORDINGS_ROOT = Path("recordings")
RECORDINGS_ROOT.mkdir(parents=True, exist_ok=True)

# 跟踪当前已连接的客户端及其录制会话
CONNECTED_CLIENTS = set()
RECORDING_SESSIONS: Dict[websockets.WebSocketServerProtocol, "RecordingSession"] = {}


class RecordingSession:
    """
    针对单个客户端的一次录制会话：
    - 在 recordings/ 下为每个会话创建独立目录
    - 将纯 H.264 比特流写入 stream.h264
    - 记录首尾帧的设备时间戳与服务器到达时间，用于事后估算 FPS
    - 结束时调用 ffmpeg 将 H.264 封装为 MP4
    """
    def __init__(self, client_id: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.client_id = client_id
        self.session_dir = RECORDINGS_ROOT / f"{client_id}_{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.raw_path = self.session_dir / "stream.h264"
        self.mp4_path = self.session_dir / "stream.mp4"
        self.thumbnail_path = self.session_dir / "thumbnail.jpg"
        self.raw_file = self.raw_path.open("wb")
        self.frame_count = 0
        self.first_device_ts_ms: Optional[int] = None
        self.last_device_ts_ms: Optional[int] = None
        self.first_arrival_ms: Optional[int] = None
        self.last_arrival_ms: Optional[int] = None

    def add_frame(self, timestamp_ms: int, arrival_ms: int, payload: bytes):
        """追加一帧 H.264 数据，并记录时间信息。"""
        self.raw_file.write(payload)
        self.frame_count += 1
        if self.first_device_ts_ms is None:
            self.first_device_ts_ms = timestamp_ms
        self.last_device_ts_ms = timestamp_ms
        if self.first_arrival_ms is None:
            self.first_arrival_ms = arrival_ms
        self.last_arrival_ms = arrival_ms

    def close(self):
        if not self.raw_file.closed:
            self.raw_file.close()

    def finalize(self) -> Optional[Path]:
        """
        结束会话：
        - 先关闭裸码流文件
        - 通过 _determine_fps() 估算实际帧率
        - 调用 mux_frames_to_mp4 使用 ffmpeg 做封装（视频已在 Android 端旋转完成）
        - 提取第一帧并保存为缩略图
        """
        self.close()
        fps = self._determine_fps()
        mp4_path = mux_frames_to_mp4(self.raw_path, self.mp4_path, fps)
        if mp4_path:
            # 提取第一帧并保存为缩略图
            extract_first_frame(self.raw_path, self.thumbnail_path)
        return mp4_path

    def _determine_fps(self) -> float:
        """
        根据记录的时间戳估算 FPS。
        - 优先使用“服务器到达时间”的估算结果（更接近服务器实际接收节奏）
        - 如果异常（太低或不可用），再退回到“设备时间戳”的估算
        - 两者都不可用时，使用保底值 10 FPS
        """
        def _calc_fps(frame_count: int, duration_ms: int) -> Optional[float]:
            if frame_count <= 1 or duration_ms <= 0:
                return None
            return frame_count / (duration_ms / 1000.0)

        def _log(label: str, fps: Optional[float]):
            if fps is None:
                print(f"[Warning]: FPS estimate ({label}) unavailable.")
                return None
            bounded = max(1.0, min(fps, 60.0))
            print(
                f"[Info]: FPS estimate ({label}) frame_count={self.frame_count} -> {bounded:.2f}"
            )
            return bounded

        fps_device = None
        fps_arrival = None

        if (
            self.first_device_ts_ms is not None
            and self.last_device_ts_ms is not None
        ):
            duration_device = max(
                self.last_device_ts_ms - self.first_device_ts_ms, 1
            )
            fps_device = _calc_fps(self.frame_count, duration_device)

        if (
            self.first_arrival_ms is not None
            and self.last_arrival_ms is not None
        ):
            duration_arrival = max(
                self.last_arrival_ms - self.first_arrival_ms, 1
            )
            fps_arrival = _calc_fps(self.frame_count, duration_arrival)

        bounded_arrival = _log("server", fps_arrival)
        if bounded_arrival and bounded_arrival > 1.5:
            return bounded_arrival

        bounded_device = _log("device", fps_device)
        if bounded_device:
            return bounded_device

        print("[Warning]: Unable to estimate FPS accurately, using fallback 10 FPS.")
        return 10.0


def parse_frame_packet(packet: bytes):
    if len(packet) < FRAME_HEADER_SIZE:
        raise ValueError("Frame packet too small to contain header")
    timestamp_ms, frame_seq, payload_length = struct.unpack(
        FRAME_HEADER_FORMAT, packet[:FRAME_HEADER_SIZE]
    )
    payload = packet[FRAME_HEADER_SIZE:]
    if payload_length != len(payload):
        raise ValueError(
            f"Payload length mismatch. Expected {payload_length}, got {len(payload)}"
        )
    # 返回：设备时间戳（ms）、帧序号、裸 H.264 数据
    return timestamp_ms, frame_seq, payload


def mux_frames_to_mp4(raw_path: Path, output_path: Path, fps: float) -> Optional[Path]:
    """
    使用 ffmpeg 将裸 H.264 比特流封装为 MP4：
    - 通过 -f h264 告诉 ffmpeg 输入格式
    - 通过 -r <fps> 显式指定帧率，避免 ffmpeg 依赖不可靠的码流推断
    - 使用 -c:v copy 直接拷贝视频轨，无重编码，速度快且无损
    - 视频已在 Android 端旋转完成，无需后端再旋转
    """
    if not raw_path.exists():
        print("[Warning]: Raw H.264 file not found; skip MP4 muxing.")
        return None

    cmd = [
        os.environ.get("FFMPEG_BIN", "ffmpeg"),
        "-y",
        "-f", "h264",
        "-r", f"{fps:.2f}",
        "-i", str(raw_path),
        "-c:v", "copy",
        str(output_path),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("[Error]: ffmpeg failed to mux MP4")
        print(result.stderr.strip())
        return None

    return output_path


def extract_first_frame(raw_path: Path, output_path: Path) -> Optional[Path]:
    """
    从 H.264 文件中提取第一帧并保存为 JPEG 图片。
    视频已在 Android 端旋转完成，无需后端再旋转。
    """
    if not raw_path.exists():
        print("[Warning]: Raw H.264 file not found; skip thumbnail extraction.")
        return None

    cmd = [
        os.environ.get("FFMPEG_BIN", "ffmpeg"),
        "-y",
        "-f", "h264",
        "-i", str(raw_path),
        "-vframes", "1",
        "-q:v", "2",  # 高质量 JPEG (2-31, 2 是最高质量)
        str(output_path),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("[Warning]: ffmpeg failed to extract thumbnail")
        print(result.stderr.strip())
        return None

    print(f"[Info]: Thumbnail saved to {output_path}")
    return output_path


def start_recording(websocket, client_id: str):
    """
    开始一个新的录制会话。
    视频已在 Android 端旋转完成，无需记录 rotation。
    """
    if websocket in RECORDING_SESSIONS:
        finalize_recording(websocket, client_id)
    session = RecordingSession(client_id)
    RECORDING_SESSIONS[websocket] = session
    print(f"[Info]: Started recording session at {session.session_dir}")


def finalize_recording(websocket, client_id: str):
    session = RECORDING_SESSIONS.pop(websocket, None)
    if not session:
        return
    mp4_path = session.finalize()
    if mp4_path:
        print(f"[Info]: MP4 saved to {mp4_path}")
    else:
        print("[Warning]: MP4 generation skipped (no frames or muxing error).")


# This handler manages receiving messages from a client
async def consumer_handler(websocket):
    """
    处理来自单个客户端的所有消息：
    - 文本消息：视为 JSON 状态（ClientStatus），用于开始 / 结束录制
    - 二进制消息：视为一帧 H.264 数据（带自定义帧头），写入对应会话
    """
    client_id = f"{websocket.remote_address[0]}_{websocket.remote_address[1]}"
    print(f"[Info]: Client {client_id} consumer handler started.")
    
    try:
        async for message in websocket:
            if isinstance(message, str):
                # 文本：来自 App 的 JSON 状态消息
                print(f"[App Status] from {client_id}: {message}")
                try:
                    data = json.loads(message)
                    status = data.get("status")
                    if status == "capture_started":
                        start_recording(websocket, client_id)
                    elif status == "capture_stopped":
                        finalize_recording(websocket, client_id)
                except (json.JSONDecodeError, TypeError):
                    # 不是我们关心的 JSON，忽略
                    pass
            else:
                # 二进制：H.264 帧（带自定义帧头）
                session = RECORDING_SESSIONS.get(websocket)
                if not session:
                    print(f"[Warning]: Received frame from {client_id} without active session.")
                    continue
                try:
                    timestamp_ms, frame_seq, payload = parse_frame_packet(message)
                except ValueError as err:
                    print(f"[Error]: Failed to parse frame from {client_id} - {err}")
                    continue
                print(
                    f"[Frame]: {client_id} seq={frame_seq} timestamp={timestamp_ms}ms size={len(payload)} bytes"
                )
                arrival_ms = int(asyncio.get_running_loop().time() * 1000)
                session.add_frame(timestamp_ms, arrival_ms, payload)

    except websockets.exceptions.ConnectionClosed as e:
        print(f"[Connection]: Client {client_id} disconnected: {e.code} {e.reason}")
    finally:
        finalize_recording(websocket, client_id)
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
        await consumer_handler(websocket)
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
                bitrate_mb = 4  # 默认 4 MB（会在客户端转换为 bps）
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
                        bitrate_mb = int(parts[2])
                        if bitrate_mb <= 0:
                            raise ValueError("Bitrate must be positive")
                    except ValueError:
                        print(
                            "[Error]: Invalid bitrate. Expecting positive integer (MB). Using default 4 MB."
                        )
                        bitrate_mb = 4

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
                    "bitrate": bitrate_mb,  # In MB, client will convert to bps
                    "fps": fps,
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
async def main(host: str = "0.0.0.0", port: int = 50001):
    server_task = websockets.serve(connection_handler, host, port)
    async with server_task:
        print(f"WebSocket server started at ws://{host}:{port}")
        print("You can now connect your Android Camera App.")
        terminal_task = asyncio.create_task(terminal_input_handler())
        await asyncio.gather(terminal_task)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=50001)
    args = parser.parse_args()

    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        print("\nServer shutting down.")
