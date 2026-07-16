"""Per-process singleton that keeps one MavlinkConnector per drone.

Rationale: pymavlink connections are UDP/TCP sockets — we do not want to open
one per request. The ConnectionManager caches connectors by ``drone_id`` and
lets endpoints reuse them for mission dispatch, RTL, etc.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.services.mavlink_connector import MavlinkConnector

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Async-safe registry of ``drone_id -> MavlinkConnector``.

    Not thread-safe across event loops. Intended for use from FastAPI request
    handlers running on the app's single asyncio loop.
    """

    _instance: "ConnectionManager | None" = None

    def __init__(self) -> None:
        self._connectors: dict[UUID, MavlinkConnector] = {}
        self._lock = asyncio.Lock()

    # -------------------------------------------------------- singleton
    @classmethod
    def instance(cls) -> "ConnectionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Test-only: drop the singleton so a fresh manager is created."""
        cls._instance = None

    # ---------------------------------------------------------------- api
    async def get_or_create(
        self,
        drone_id: UUID,
        endpoint: str,
        redis_client: Any = None,
    ) -> MavlinkConnector:
        """Return the cached connector or build+connect a new one.

        The caller is responsible for scheduling ``connector.run()`` if a
        background read loop is required; for mission dispatch we only need a
        live socket, so we call :meth:`MavlinkConnector.connect` (blocking).
        """
        async with self._lock:
            existing = self._connectors.get(drone_id)
            if existing is not None:
                return existing

            connector = MavlinkConnector(
                endpoint=endpoint, redis_client=redis_client
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, connector.connect)
            self._connectors[drone_id] = connector
            logger.info(
                "ConnectionManager: opened MAVLink %s for drone %s",
                endpoint, drone_id,
            )
            return connector

    def get(self, drone_id: UUID) -> MavlinkConnector | None:
        return self._connectors.get(drone_id)

    async def close(self, drone_id: UUID) -> None:
        async with self._lock:
            connector = self._connectors.pop(drone_id, None)
        if connector is None:
            return
        try:
            connector.stop()
            conn = getattr(connector, "_conn", None)
            close_fn = getattr(conn, "close", None)
            if callable(close_fn):
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, close_fn)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ConnectionManager: error closing connector for drone %s",
                drone_id,
            )

    async def close_all(self) -> None:
        drone_ids = list(self._connectors.keys())
        for drone_id in drone_ids:
            await self.close(drone_id)
        logger.info("ConnectionManager: closed %d connector(s)", len(drone_ids))
