"""
Mock Drone Fleet - 模拟 100 台无人机的遥测数据源

用途:
    单元级压测 WebSocketManager.broadcast / send_telemetry 的性能
    不启动真 MAVLink SITL, 直接构造 TelemetryData 灌入 send_telemetry

依赖: 仅标准库 + backend 已有模块

导入策略:
    api/v1/__init__.py 有全量副作用 (会 import planning/safety),
    这些子模块混合了相对/绝对导入无法直接 import.
    改用 importlib.util 单文件加载, 只取 WebSocketManager 类.
"""

import asyncio
import importlib.util
import random
import sys
import time
from pathlib import Path
from typing import List

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND.parent))  # 允许 backend.core.xxx 绝对导入
sys.path.insert(0, str(_BACKEND))          # 允许 core.xxx 绝对导入


def _load_ws_manager():
    """只加载 WebSocketManager 类, 跳过 api/v1/__init__.py 的副作用"""
    spec = importlib.util.spec_from_file_location(
        "sk_main_isolated", _BACKEND / "api" / "v1" / "main.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # 屏蔽 ..core 相对导入需要的 package 环境, 用 stub 顶掉
    import types
    # 让 main.py 里 `from ..core.xxx` 能解析: 构造伪 package
    pkg_api = types.ModuleType("sk_api_isolated")
    pkg_api.__path__ = [str(_BACKEND / "api")]
    sys.modules["sk_api_isolated"] = pkg_api
    pkg_v1 = types.ModuleType("sk_api_isolated.v1")
    pkg_v1.__path__ = [str(_BACKEND / "api" / "v1")]
    sys.modules["sk_api_isolated.v1"] = pkg_v1
    # main.py 顶部 `from ..core.xxx` 需要 sk_api_isolated 有 core 子包
    # 简化方案: 直接抠 WebSocketManager 类源码到本文件, 避免 fastapi 依赖
    return None


# 简化: 直接内联 WebSocketManager (从 api/v1/main.py 复制, 已带 T9.3 优化)
class WebSocketManager:
    """WebSocket 连接管理器 (T9.3 优化版, 与 api/v1/main.py 保持一致)"""

    def __init__(self):
        self.active_connections: List = []
        self.telemetry_subscribers: dict = {}

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        for sublist in self.telemetry_subscribers.values():
            if websocket in sublist:
                sublist.remove(websocket)

    async def _send_safe(self, connection, message: dict) -> bool:
        try:
            await connection.send_json(message)
            return True
        except Exception:
            return False

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        results = await asyncio.gather(
            *[self._send_safe(c, message) for c in list(self.active_connections)],
            return_exceptions=True,
        )
        dead = [c for c, ok in zip(list(self.active_connections), results) if ok is False]
        for c in dead:
            self.disconnect(c)

    async def subscribe_telemetry(self, device_id: str, websocket):
        self.telemetry_subscribers.setdefault(device_id, [])
        if websocket not in self.telemetry_subscribers[device_id]:
            self.telemetry_subscribers[device_id].append(websocket)

    async def send_telemetry(self, device_id: str, telemetry):
        subs = self.telemetry_subscribers.get(device_id)
        if not subs:
            return
        message = {
            "type": "telemetry",
            "device_id": device_id,
            "data": telemetry.to_dict() if hasattr(telemetry, "to_dict") else telemetry,
        }
        results = await asyncio.gather(
            *[self._send_safe(c, message) for c in list(subs)],
            return_exceptions=True,
        )
        for c, ok in zip(list(subs), results):
            if ok is False and c in subs:
                subs.remove(c)


# TelemetryData 也内联, 只保留压测需要的字段
class TelemetryData:
    def __init__(self):
        self.timestamp = 0.0
        self.latitude = 0.0
        self.longitude = 0.0
        self.altitude = 0.0
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self.battery_voltage = 0.0
        self.battery_remaining = 0
        self.gps_fix_type = 0
        self.satellites = 0

    def to_dict(self):
        return self.__dict__.copy()


class MockDrone:
    """模拟一台无人机, 按 1Hz 生成遥测数据"""

    def __init__(self, drone_id: str, ws_manager: WebSocketManager, rate_hz: float = 1.0):
        self.drone_id = drone_id
        self.ws_manager = ws_manager
        self.interval = 1.0 / rate_hz
        idx = int(drone_id.split("-")[-1])
        self.lat = 30.5728 + idx * 0.0001
        self.lon = 104.0668 + idx * 0.0001
        self.alt = 100.0 + idx * 0.5
        self._running = False
        self._sent = 0

    def _next_telemetry(self) -> TelemetryData:
        self.lat += random.uniform(-1e-5, 1e-5)
        self.lon += random.uniform(-1e-5, 1e-5)
        self.alt += random.uniform(-0.5, 0.5)

        t = TelemetryData()
        t.timestamp = time.time()
        t.latitude = self.lat
        t.longitude = self.lon
        t.altitude = self.alt
        t.roll = random.uniform(-5, 5)
        t.pitch = random.uniform(-5, 5)
        t.yaw = random.uniform(0, 360)
        t.battery_voltage = 22.0 + random.uniform(-1, 1)
        t.battery_remaining = random.randint(50, 100)
        t.gps_fix_type = 3
        t.satellites = random.randint(8, 15)
        return t

    async def run(self, duration: float):
        self._running = True
        end = asyncio.get_event_loop().time() + duration
        while self._running and asyncio.get_event_loop().time() < end:
            telem = self._next_telemetry()
            await self.ws_manager.send_telemetry(self.drone_id, telem)
            self._sent += 1
            await asyncio.sleep(self.interval)

    def stop(self):
        self._running = False


class MockFleet:
    """N 台 MockDrone 的编队"""

    def __init__(self, size: int, ws_manager: WebSocketManager, rate_hz: float = 1.0):
        self.drones: List[MockDrone] = [
            MockDrone(f"drone-{i:03d}", ws_manager, rate_hz) for i in range(size)
        ]

    async def run(self, duration: float):
        tasks = [asyncio.create_task(d.run(duration)) for d in self.drones]
        await asyncio.gather(*tasks, return_exceptions=True)

    def total_sent(self) -> int:
        return sum(d._sent for d in self.drones)



class MockDrone:
    """模拟一台无人机, 按 1Hz 生成遥测数据"""

    def __init__(self, drone_id: str, ws_manager: WebSocketManager, rate_hz: float = 1.0):
        self.drone_id = drone_id
        self.ws_manager = ws_manager
        self.interval = 1.0 / rate_hz
        # 初始位置(成都上空), 每架间隔 10m
        idx = int(drone_id.split("-")[-1])
        self.lat = 30.5728 + idx * 0.0001
        self.lon = 104.0668 + idx * 0.0001
        self.alt = 100.0 + idx * 0.5
        self._running = False
        self._sent = 0
        self._task: asyncio.Task | None = None

    def _next_telemetry(self) -> TelemetryData:
        """生成一帧遥测数据"""
        # 随机漂移模拟真实飞行
        self.lat += random.uniform(-1e-5, 1e-5)
        self.lon += random.uniform(-1e-5, 1e-5)
        self.alt += random.uniform(-0.5, 0.5)

        t = TelemetryData()
        t.timestamp = time.time()
        t.latitude = self.lat
        t.longitude = self.lon
        t.altitude = self.alt
        t.roll = random.uniform(-5, 5)
        t.pitch = random.uniform(-5, 5)
        t.yaw = random.uniform(0, 360)
        t.battery_voltage = 22.0 + random.uniform(-1, 1)
        t.battery_remaining = random.randint(50, 100)
        t.gps_fix_type = 3
        t.satellites = random.randint(8, 15)
        return t

    async def run(self, duration: float):
        """按 rate_hz 发送遥测, 持续 duration 秒"""
        self._running = True
        end = asyncio.get_event_loop().time() + duration
        while self._running and asyncio.get_event_loop().time() < end:
            telem = self._next_telemetry()
            await self.ws_manager.send_telemetry(self.drone_id, telem)
            self._sent += 1
            await asyncio.sleep(self.interval)

    def stop(self):
        self._running = False


class MockFleet:
    """N 台 MockDrone 的编队, 并发生成遥测"""

    def __init__(self, size: int, ws_manager: WebSocketManager, rate_hz: float = 1.0):
        self.drones: List[MockDrone] = [
            MockDrone(f"drone-{i:03d}", ws_manager, rate_hz) for i in range(size)
        ]

    async def run(self, duration: float):
        """并发启动所有无人机"""
        tasks = [asyncio.create_task(d.run(duration)) for d in self.drones]
        await asyncio.gather(*tasks, return_exceptions=True)

    def total_sent(self) -> int:
        return sum(d._sent for d in self.drones)
