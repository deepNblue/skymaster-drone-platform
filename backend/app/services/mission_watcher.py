"""Mission-event watcher — turns FakeDrone `mission_completed` polls into
Redis pub/sub events so the frontend can subscribe via WebSocket.

Runs as a lifespan background task in dev/sim mode. For each registered
sim drone it polls `/state` every 500ms; when it sees the rising edge of
``mission_completed`` it publishes on ``mission.event.{sysid}``.

Frontends can subscribe via WS `/api/v1/ws/events` (see websocket.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MissionWatcher:
    def __init__(
        self,
        redis_client: Any,
        registry: dict[int, int],
        poll_interval_s: float = 0.5,
    ) -> None:
        self.redis = redis_client
        self.registry = registry
        self.poll_interval_s = poll_interval_s
        self._stop = asyncio.Event()
        # sysid -> last mission_completed_at we've broadcast about
        self._last_completed_ts: dict[int, float] = {}

    async def run(self) -> None:
        logger.info(
            "MissionWatcher polling %d drones every %.2fs",
            len(self.registry),
            self.poll_interval_s,
        )
        while not self._stop.is_set():
            try:
                await self._poll_all()
            except Exception:  # noqa: BLE001
                logger.exception("MissionWatcher poll loop error")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.poll_interval_s
                )
            except asyncio.TimeoutError:
                continue

    async def _poll_all(self) -> None:
        loop = asyncio.get_running_loop()
        for sysid, port in self.registry.items():
            try:
                state = await loop.run_in_executor(None, self._get_state, port)
            except Exception:
                continue
            if not state:
                continue
            completed_at = state.get("mission_completed_at")
            if not completed_at:
                continue
            last = self._last_completed_ts.get(sysid)
            if last == completed_at:
                continue
            # Rising edge!
            self._last_completed_ts[sysid] = completed_at
            payload = {
                "type": "mission.completed",
                "sysid": sysid,
                "mission_progress": state.get("mission_progress"),
                "completed_at": completed_at,
                "ts": time.time(),
            }
            channel = f"mission.event.{sysid}"
            try:
                await self.redis.publish(channel, json.dumps(payload))
                # Also publish on a global channel for the events WS
                await self.redis.publish("mission.event.all", json.dumps(payload))
                logger.info("MissionWatcher published %s on %s", payload, channel)
            except Exception:  # noqa: BLE001
                logger.exception("MissionWatcher publish failed")

    @staticmethod
    def _get_state(port: int) -> Optional[dict]:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/state", timeout=1.5
            ) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return None

    def stop(self) -> None:
        self._stop.set()
