"""
Mock WebSocket Client - 模拟前端订阅者

用途:
    在压测中扮演前端角色, 订阅 N 架无人机的遥测, 统计接收延迟

不使用真 WebSocket 网络栈, 直接实现 send_json 协议
"""

import asyncio
import time
from typing import List


class MockWebSocket:
    """模拟 FastAPI WebSocket 对象的最小接口

    仅实现被 WebSocketManager 调用的方法:
        - accept()      : 建连
        - send_json()   : 发消息
        - close()       : 断连
    """

    def __init__(self, client_id: str, drop_rate: float = 0.0):
        self.client_id = client_id
        self.drop_rate = drop_rate  # 模拟丢包/断连率
        self.accepted = False
        self.closed = False
        self.received: List[dict] = []
        self.latencies_ms: List[float] = []
        self._sent_count = 0

    async def accept(self):
        self.accepted = True

    async def send_json(self, message: dict):
        """接收消息; 记录延迟"""
        if self.closed:
            raise ConnectionError(f"Client {self.client_id} closed")

        # 模拟随机断连
        if self.drop_rate > 0:
            import random
            if random.random() < self.drop_rate:
                self.closed = True
                raise ConnectionError(f"Simulated drop on {self.client_id}")

        # 计算端到端延迟(基于遥测 timestamp)
        now = time.time()
        data = message.get("data", {})
        ts = data.get("timestamp")
        if ts:
            self.latencies_ms.append((now - ts) * 1000.0)

        self.received.append(message)
        self._sent_count += 1

    async def close(self):
        self.closed = True


class MockClient:
    """模拟一个前端用户: 订阅 K 架无人机"""

    def __init__(self, client_id: str, subscribe_drone_ids: List[str], ws_manager, drop_rate: float = 0.0):
        self.client_id = client_id
        self.subscribe_ids = subscribe_drone_ids
        self.ws_manager = ws_manager
        self.ws = MockWebSocket(client_id, drop_rate=drop_rate)

    async def connect(self):
        """建连 + 订阅"""
        await self.ws_manager.connect(self.ws)
        for did in self.subscribe_ids:
            await self.ws_manager.subscribe_telemetry(did, self.ws)

    async def disconnect(self):
        self.ws_manager.disconnect(self.ws)
        await self.ws.close()

    @property
    def received_count(self) -> int:
        return len(self.ws.received)

    @property
    def latencies_ms(self) -> List[float]:
        return self.ws.latencies_ms
