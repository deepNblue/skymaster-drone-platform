"""
In-process Async Broadcaster · v2.1 SSE 通路重构基石

问题:
    v2.0 SSE 端点 (scenes.py L374-L398) 每个订阅端起 30 分钟循环 poll DB:

        for _ in range(30*60):
            fresh = (await db.execute(select(Scene).where(...))).scalar_one_or_none()
            yield f"data: {json.dumps(snap)}\n\n"
            await asyncio.sleep(1.0)

    100 客户端同时观看 = 100 个 DB 连接每秒 poll,
    500 客户端 = DB 连接池被打爆.

方案:
    引入 in-process pub/sub Broadcaster:
      - Scene 状态变更时 (scene_job.complete / heartbeat) 主动 publish
      - SSE 端点从 poll 改为 subscribe queue
      - 单机实例内共享一个 Broadcaster instance
      - v2.2 若需跨机, 再把 impl 换成 Redis Pub/Sub (接口不变)

设计:
    - 无外部依赖 (纯 asyncio + collections)
    - 按 topic (通常是 str(scene_id)) 分组
    - 满队列 non-block 丢弃 (slow consumer 不阻塞 publisher)
    - subscribe() 返回 async generator, 直接用于 SSE yield

使用 (SSE 端点侧):
    from app.services.async_broadcaster import get_broadcaster

    br = get_broadcaster()
    async for event in br.subscribe(str(scene_id), initial=snapshot):
        yield f"data: {json.dumps(event)}\n\n"
        if event.get("status") in TERMINAL:
            break

使用 (业务侧, scene_job / worker):
    from app.services.async_broadcaster import get_broadcaster

    br = get_broadcaster()
    await br.publish(str(scene.id), {"status": "training", ...})
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import AsyncIterator, Optional


logger = logging.getLogger(__name__)


class AsyncBroadcaster:
    """
    In-process async pub/sub broadcaster.

    Not thread-safe by design — assumes single-loop asyncio usage
    (FastAPI + uvicorn default).
    """

    #: 每订阅者最大挤压深度. 满则丢弃新事件, 打日志.
    DEFAULT_QUEUE_SIZE = 128

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._queue_size = queue_size
        self._published = 0
        self._dropped = 0

    # ---------- publish side ------------------------------------------

    async def publish(self, topic: str, event: dict) -> int:
        """
        向 topic 广播 event, 返回投递成功的订阅者数.
        满队列的订阅者会被跳过 (counted as dropped).
        """
        subs = list(self._subscribers.get(topic, ()))
        if not subs:
            return 0

        delivered = 0
        for q in subs:
            try:
                q.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                self._dropped += 1
                logger.warning(
                    "broadcaster: dropped event on topic=%s (subscriber queue full)",
                    topic,
                )

        self._published += delivered
        return delivered

    # ---------- subscribe side ----------------------------------------

    async def subscribe(
        self,
        topic: str,
        *,
        initial: Optional[dict] = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[dict]:
        """
        订阅 topic. 返回 async generator.
        - initial: 建立订阅时立即 yield 的首帧 (通常是当前快照)
        - heartbeat_interval: 静默超时后 yield None, 上层可发 SSE keepalive

        用法:
            async for event in br.subscribe(topic, initial=snapshot):
                if event is None:
                    yield ": keepalive\\n\\n"
                    continue
                yield f"data: {json.dumps(event)}\\n\\n"
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers[topic].add(q)
        try:
            if initial is not None:
                yield initial

            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=heartbeat_interval)
                    yield event
                except asyncio.TimeoutError:
                    # 用 None 通知上层发 keepalive
                    yield None
        finally:
            self._subscribers[topic].discard(q)
            if not self._subscribers[topic]:
                # 无订阅时清掉 key 避免长期漂移
                self._subscribers.pop(topic, None)

    # ---------- introspection -----------------------------------------

    def stats(self) -> dict:
        return {
            "topics": len(self._subscribers),
            "subscribers": sum(len(s) for s in self._subscribers.values()),
            "published_total": self._published,
            "dropped_total": self._dropped,
        }

    def topic_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, ()))


# ---------- module singleton ----------------------------------------------

_broadcaster: Optional[AsyncBroadcaster] = None


def get_broadcaster() -> AsyncBroadcaster:
    """全局单例. FastAPI 通过 Depends 或直接 import 获取."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = AsyncBroadcaster()
    return _broadcaster


def reset_broadcaster() -> None:
    """测试用: 强制丢弃单例."""
    global _broadcaster
    _broadcaster = None
