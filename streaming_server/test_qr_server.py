import asyncio
import base64
import datetime
import json
from pathlib import Path
from typing import Set

import websockets


SAVE_DIR = Path("qr_test_segments")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

CONNECTED: Set[websockets.WebSocketServerProtocol] = set()


async def broadcast(message: str):
    if not CONNECTED:
        print("[Broadcast] No clients connected.")
        return
    print(f"[Broadcast] -> {len(CONNECTED)} client(s): {message}")
    await asyncio.gather(
        *[ws.send(message) for ws in list(CONNECTED)],
        return_exceptions=True,
    )


async def terminal_input():
    loop = asyncio.get_running_loop()
    while True:
        try:
            cmd = await loop.run_in_executor(
                None,
                lambda: input(
                    "\nEnter command ('start [w]:[h] [bitrate_mb] [fps]' or 'stop'):\n"
                    "  Example: start 4:3 4 10\n> "
                ).strip(),
            )
            if not cmd:
                continue
            parts = cmd.lower().split()
            if parts[0] == "stop":
                await broadcast(json.dumps({"command": "stop_capture"}))
            elif parts[0] == "start":
                aspect = None
                bitrate_mb = 1
                fps = 0
                if len(parts) > 1:
                    try:
                        w, h = parts[1].split(":")
                        aspect = {"width": int(w), "height": int(h)}
                    except Exception:
                        print("[Warn] Invalid aspect ratio, skip forcing aspectRatio.")
                if len(parts) > 2:
                    try:
                        bitrate_mb = float(parts[2])
                    except Exception:
                        print("[Warn] Invalid bitrate, using default 1 MB.")
                        bitrate_mb = 1
                if len(parts) > 3:
                    try:
                        fps = int(parts[3])
                    except Exception:
                        print("[Warn] Invalid fps, using 0 (unlimited).")
                        fps = 0

                payload = {
                    "format": "h264",
                    "bitrate": bitrate_mb,
                    "fps": fps,
                    "segmentDuration": 15.0,
                }
                if aspect:
                    payload["aspectRatio"] = aspect
                await broadcast(json.dumps({"command": "start_capture", "payload": payload}))
            else:
                print("[Warn] Unknown command, use 'start' or 'stop'.")
        except (asyncio.CancelledError, KeyboardInterrupt):
            break
        except Exception as e:
            print(f"[Error] terminal input: {e}")


async def handler(websocket):
    CONNECTED.add(websocket)
    client_id = f"{websocket.remote_address}"
    print(f"[Conn] {client_id} connected. total={len(CONNECTED)}")
    try:
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except Exception:
                    continue

                if data.get("type") != "mp4_segment":
                    continue

                segment_id = data.get("segment_id", "unknown")
                base64_data = data.get("data", "")
                qr_results = data.get("qr_results", [])

                try:
                    mp4_bytes = base64.b64decode(base64_data)
                except Exception as e:
                    print(f"[WARN] Failed to decode segment {segment_id}: {e}")
                    continue

                if len(mp4_bytes) == 0:
                    ts = datetime.datetime.now().isoformat()
                    print(f"[{ts}] segment={segment_id} is empty, skip writing. qr_results={qr_results}")
                    continue

                out_path = SAVE_DIR / f"{segment_id}.mp4"
                out_path.write_bytes(mp4_bytes)

                ts = datetime.datetime.now().isoformat()
                print(f"[{ts}] segment={segment_id} size={len(mp4_bytes)} qr_results={qr_results}")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"[Conn] {client_id} closed: {e}")
        except ConnectionResetError as e:
            print(f"[Conn] {client_id} reset: {e}")
        print("client disconnected")
    finally:
        CONNECTED.discard(websocket)
        print(f"[Conn] {client_id} removed. total={len(CONNECTED)}")


async def main():
    # 提高 max_size，避免 Base64 后的 MP4 分段触发 1009 断开（原 10MB 不足以容纳较长分段）
    server = websockets.serve(handler, "0.0.0.0", 50003, max_size=20 * 1024 * 1024)
    async with server:
        print("Test server running at ws://0.0.0.0:50003")
        term_task = asyncio.create_task(terminal_input())
        await asyncio.gather(term_task)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Test server stopped.")

