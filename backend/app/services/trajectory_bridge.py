"""Background bridge: Redis pub/sub `telemetry.broadcast.*` → TrajectoryStore.

Runs as an asyncio task inside the FastAPI lifespan when
``ENABLE_TRAJECTORY_STORE=true`` (default: true in dev_stack).

Uses psubscribe so we automatically pick up new drones without polling.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.services.trajectory_store import TrajectoryStore

logger = logging.getLogger(__name__)


class TrajectoryBridge:
    def __init__(self, redis_client: Any, store: TrajectoryStore) -> None:
        self.redis = redis_client
        self.store = store
        self._task: asyncio.Task | None = None
        self._stop_evt = asyncio.Event()

    async def run(self) -> None:
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe("telemetry.broadcast.*")
        logger.info("TrajectoryBridge subscribed to telemetry.broadcast.*")
        try:
            while not self._stop_evt.is_set():
                try:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                except Exception:
                    logger.exception("TrajectoryBridge get_message failed")
                    await asyncio.sleep(1)
                    continue
                if not msg:
                    continue
                try:
                    channel = msg.get("channel")
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    # channel = "telemetry.broadcast.<drone_id>"
                    drone_id = channel.rsplit(".", 1)[-1] if channel else ""
                    if not drone_id:
                        continue
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode()
                    if isinstance(data, str):
                        payload = json.loads(data)
                    elif isinstance(data, dict):
                        payload = data
                    else:
                        continue
                    await self.store.ingest(drone_id, payload)
                except Exception:
                    logger.exception("TrajectoryBridge ingest failed")
        finally:
            try:
                await pubsub.punsubscribe("telemetry.broadcast.*")
                await pubsub.aclose()
            except Exception:
                logger.debug("TrajectoryBridge cleanup swallowed", exc_info=True)

    def stop(self) -> None:
        self._stop_evt.set()
