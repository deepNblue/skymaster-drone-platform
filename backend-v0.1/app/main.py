"""FastAPI application entrypoint for SkyMaster v0.1."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.db import engine
from app.services.connection_manager import ConnectionManager
from app.services.fake_redis_singleton import get_redis, is_fake_enabled

logger = logging.getLogger(__name__)


def _consumer_enabled() -> bool:
    return os.getenv("START_TELEMETRY_CONSUMER", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _mavlink_enabled() -> bool:
    return os.getenv("START_MAVLINK_CONNECTOR", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _trajectory_enabled() -> bool:
    return os.getenv("ENABLE_TRAJECTORY_STORE", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Init/close database engine, redis client, and optional consumer task."""
    # Redis client lives on app.state for dependency access. When
    # USE_FAKE_REDIS=true we use the in-process fakeredis singleton so the
    # mavlink connector, telemetry consumer, and WS pub/sub all share one
    # in-memory server (streams + pub/sub must round-trip through the same
    # backend to work).
    if is_fake_enabled():
        app.state.redis = get_redis()
        logger.info("Using fakeredis (USE_FAKE_REDIS=true) — in-memory only")
    else:
        app.state.redis = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )

    # Per-process MAVLink connection registry — used by mission dispatch.
    app.state.connection_manager = ConnectionManager.instance()

    consumer_task: asyncio.Task | None = None
    consumer_instance = None
    if _consumer_enabled():
        # Local import — avoids pulling the DB session factory in tests that
        # never touch telemetry.
        from app.services.telemetry_consumer import TelemetryConsumer

        consumer_instance = TelemetryConsumer(
            redis_client=app.state.redis,
            batch_size=int(os.getenv("TELEMETRY_BATCH_SIZE", "100")),
            flush_ms=int(os.getenv("TELEMETRY_FLUSH_MS", "5000")),
            stream_prefix=os.getenv("TELEMETRY_STREAM_PREFIX", "telemetry:"),
        )
        consumer_task = asyncio.create_task(
            consumer_instance.run(), name="telemetry-consumer"
        )
        logger.info("Telemetry consumer background task started")

    mavlink_task: asyncio.Task | None = None
    mavlink_instance = None
    if _mavlink_enabled():
        from app.services.mavlink_connector import MavlinkConnector

        mavlink_instance = MavlinkConnector(
            endpoint=os.getenv("MAVLINK_ENDPOINT", "udpin:0.0.0.0:14550"),
            redis_client=app.state.redis,
            publish_interval_ms=int(os.getenv("TELEMETRY_PUBLISH_MS", "500")),
        )
        mavlink_task = asyncio.create_task(
            mavlink_instance.run(), name="mavlink-connector"
        )
        logger.info("MAVLink connector background task started")

    trajectory_task: asyncio.Task | None = None
    trajectory_bridge = None
    trajectory_store = None
    if _trajectory_enabled():
        from app.services.trajectory_bridge import TrajectoryBridge
        from app.services.trajectory_store import get_store

        trajectory_store = get_store()
        await trajectory_store.start()
        app.state.trajectory_store = trajectory_store
        trajectory_bridge = TrajectoryBridge(
            redis_client=app.state.redis, store=trajectory_store,
        )
        trajectory_task = asyncio.create_task(
            trajectory_bridge.run(), name="trajectory-bridge",
        )
        logger.info("TrajectoryStore + Bridge started")

    mission_watcher_task: asyncio.Task | None = None
    mission_watcher = None
    if os.getenv("ENABLE_MISSION_WATCHER", "true").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        from app.services.mission_watcher import MissionWatcher
        from app.api.v1.sim import _default_registry as _sim_registry

        mission_watcher = MissionWatcher(
            redis_client=app.state.redis, registry=_sim_registry()
        )
        mission_watcher_task = asyncio.create_task(
            mission_watcher.run(), name="mission-watcher",
        )
        logger.info("MissionWatcher started")

    uom_adapter = None
    if os.getenv("ENABLE_UOM", "true").strip().lower() in ("1", "true", "yes", "on"):
        from app.services.uom_adapter import get_uom

        uom_adapter = get_uom()
        await uom_adapter.start()
        app.state.uom = uom_adapter
        logger.info("UOM adapter started")

    # ---- R12: RevokedToken cleanup periodic task -------------------------
    revoke_cleanup_task: asyncio.Task | None = None
    if os.getenv("ENABLE_REVOKED_TOKEN_CLEANUP", "true").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        from app.services.revoked_token_cleanup import cleanup_expired_revocations

        async def _revoke_cleanup_loop() -> None:
            interval_h = int(os.getenv("REVOKED_TOKEN_CLEANUP_HOURS", "6"))
            while True:
                try:
                    await cleanup_expired_revocations()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("revoked_token cleanup failed: %s", exc)
                await asyncio.sleep(interval_h * 3600)

        revoke_cleanup_task = asyncio.create_task(
            _revoke_cleanup_loop(), name="revoked-token-cleanup",
        )
        logger.info("RevokedToken cleanup task started (every 6h)")

    try:
        yield
    finally:
        if revoke_cleanup_task is not None:
            revoke_cleanup_task.cancel()
            try:
                await revoke_cleanup_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        for inst, task in (
            (consumer_instance, consumer_task),
            (mavlink_instance, mavlink_task),
            (trajectory_bridge, trajectory_task),
            (mission_watcher, mission_watcher_task),
        ):
            if task is not None and inst is not None:
                try:
                    inst.stop()
                except Exception:  # noqa: BLE001
                    pass
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        if trajectory_store is not None:
            try:
                await trajectory_store.stop()
            except Exception:  # noqa: BLE001
                pass
        if uom_adapter is not None:
            try:
                await uom_adapter.stop()
            except Exception:  # noqa: BLE001
                pass
        await app.state.redis.close()
        await engine.dispose()


app = FastAPI(
    title="SkyMaster API",
    version="0.1.0",
    description="SkyMaster drone platform API · v0.1 MVP",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Hook the async session factory onto app.state so audit middleware
# (and other services) can write to the DB without importing the
# session module directly.
from app.db import AsyncSessionLocal as _AsyncSessionLocal  # noqa: E402
app.state.async_sessionmaker = _AsyncSessionLocal

if os.getenv("ENABLE_AUDIT_MIDDLEWARE", "true").strip().lower() in (
    "1", "true", "yes", "on",
):
    from app.services.audit_middleware import AuditMiddleware, InMemoryAuditSink

    app.add_middleware(AuditMiddleware)
    if os.getenv("AUDIT_MEMORY_SINK", "false").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        app.state.audit_sink = InMemoryAuditSink()

# Prometheus metrics middleware — v1.0 monitoring track.
if os.getenv("ENABLE_METRICS", "true").strip().lower() in (
    "1", "true", "yes", "on",
):
    from app.services.metrics import MetricsMiddleware

    app.add_middleware(MetricsMiddleware)

app.include_router(api_router, prefix="/api/v1")
