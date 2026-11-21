"""
Test WebSocket Server - 真 FastAPI + uvicorn 的轻量测试服务器

只挂载 /ws 端点 + 内部启动 100 台 MockDrone 作为遥测源。
不含 DeviceManager / MissionPlanner 等真业务组件。

用途:
    真 TCP + WebSocket 网络栈压测,
    验证 100 客户端连接本机 8765 端口订阅遥测的实际延迟。

启动:
    python3 -m backend.tests.load.ws_server --drones 100 --port 8765
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 允许直接跑
_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND.parent))
sys.path.insert(0, str(_BACKEND))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from backend.tests.load.mock_drone import MockFleet, WebSocketManager

logging.basicConfig(level=logging.WARNING)  # 减少日志噪声

app = FastAPI(title="SkyMaster Load Test Server")
ws_manager = WebSocketManager()
_fleet: MockFleet | None = None
_fleet_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup():
    global _fleet, _fleet_task
    drones = int(app.state.drones)
    duration = float(app.state.duration)
    rate = float(app.state.rate)
    _fleet = MockFleet(size=drones, ws_manager=ws_manager, rate_hz=rate)
    _fleet_task = asyncio.create_task(_fleet.run(duration))
    print(f"[server] Fleet started: {drones} drones @ {rate}Hz for {duration}s")


@app.on_event("shutdown")
async def shutdown():
    if _fleet:
        for d in _fleet.drones:
            d.stop()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "drones": len(_fleet.drones) if _fleet else 0,
        "connections": len(ws_manager.active_connections),
        "total_sent": _fleet.total_sent() if _fleet else 0,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """接受连接 -> 处理 subscribe_telemetry / ping"""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                mtype = msg.get("type")
                if mtype == "subscribe_telemetry":
                    device_id = msg.get("device_id")
                    if device_id:
                        await ws_manager.subscribe_telemetry(device_id, websocket)
                        await websocket.send_json({"type": "subscribed", "device_id": device_id})
                elif mtype == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--drones", type=int, default=100)
    ap.add_argument("--rate", type=float, default=1.0)
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    app.state.drones = args.drones
    app.state.rate = args.rate
    app.state.duration = args.duration

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
