"""
Test REST + WS Server - 真 FastAPI + uvicorn 综合测试服务器

在 ws_server 基础上加挂 REST 端点, 用 MockFleet 内存数据源:
  GET  /api/devices              列表
  GET  /api/devices/{id}         详情
  GET  /api/devices/{id}/telemetry 最新遥测
  GET  /api/statistics           全局统计
  GET  /health                   健康检查
  WS   /ws                       WebSocket 遥测订阅

用途:
    真 HTTP 请求栈压测,
    验证 REST API 在 100 机场景下的响应延迟.

启动:
    python3 -m backend.tests.load.api_server --drones 100 --duration 120 --port 8766
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND.parent))
sys.path.insert(0, str(_BACKEND))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
import uvicorn

from backend.tests.load.mock_drone import MockFleet, WebSocketManager

logging.basicConfig(level=logging.WARNING)

app = FastAPI(title="SkyMaster Load Test API Server")
ws_manager = WebSocketManager()
_fleet: MockFleet | None = None
_fleet_task: asyncio.Task | None = None
_latest_telemetry: dict = {}  # {drone_id: TelemetryData}


@app.on_event("startup")
async def startup():
    global _fleet, _fleet_task
    drones = int(app.state.drones)
    duration = float(app.state.duration)
    rate = float(app.state.rate)
    _fleet = MockFleet(size=drones, ws_manager=ws_manager, rate_hz=rate)

    # 包装 send_telemetry 以捕获最新遥测 (供 REST /api/devices/{id}/telemetry)
    orig_send = ws_manager.send_telemetry

    async def hooked_send(device_id, telemetry):
        _latest_telemetry[device_id] = telemetry
        await orig_send(device_id, telemetry)

    ws_manager.send_telemetry = hooked_send

    _fleet_task = asyncio.create_task(_fleet.run(duration))
    print(f"[server] Fleet started: {drones} drones @ {rate}Hz for {duration}s")


@app.on_event("shutdown")
async def shutdown():
    if _fleet:
        for d in _fleet.drones:
            d.stop()


# ===================== REST 端点 =====================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "drones": len(_fleet.drones) if _fleet else 0,
        "connections": len(ws_manager.active_connections),
        "total_sent": _fleet.total_sent() if _fleet else 0,
    }


@app.get("/api/devices")
async def list_devices():
    """设备列表"""
    if not _fleet:
        return []
    return [
        {
            "device_id": d.drone_id,
            "status": "online",
            "latitude": d.lat,
            "longitude": d.lon,
            "altitude": d.alt,
        }
        for d in _fleet.drones
    ]


@app.get("/api/devices/{device_id}")
async def get_device(device_id: str):
    """设备详情"""
    if not _fleet:
        raise HTTPException(404, "Fleet not started")
    for d in _fleet.drones:
        if d.drone_id == device_id:
            return {
                "device_id": d.drone_id,
                "status": "online",
                "latitude": d.lat,
                "longitude": d.lon,
                "altitude": d.alt,
                "sent_count": d._sent,
            }
    raise HTTPException(404, f"Device {device_id} not found")


@app.get("/api/devices/{device_id}/telemetry")
async def get_telemetry(device_id: str):
    """最新遥测"""
    telem = _latest_telemetry.get(device_id)
    if telem is None:
        raise HTTPException(404, f"No telemetry yet for {device_id}")
    return telem.to_dict()


@app.get("/api/statistics")
async def statistics():
    """全局统计"""
    if not _fleet:
        return {"drones": 0, "total_sent": 0}
    return {
        "drones": len(_fleet.drones),
        "total_sent": _fleet.total_sent(),
        "active_connections": len(ws_manager.active_connections),
        "subscribers": sum(len(v) for v in ws_manager.telemetry_subscribers.values()),
        "server_time": time.time(),
    }


# ===================== WebSocket 端点 =====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "subscribe_telemetry":
                    did = msg.get("device_id")
                    if did:
                        await ws_manager.subscribe_telemetry(did, websocket)
                        await websocket.send_json({"type": "subscribed", "device_id": did})
                elif msg.get("type") == "ping":
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
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args()

    app.state.drones = args.drones
    app.state.rate = args.rate
    app.state.duration = args.duration

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
