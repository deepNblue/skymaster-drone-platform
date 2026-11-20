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


def _real_gs_executors_enabled() -> bool:
    """Enable real subprocess-based COLMAP/Gsplat executors (default: off).

    Requires COLMAP + gsplat/nerfstudio installed in the execution environment.
    When off (default), NoOpExecutor is used for dev/test.
    """
    return os.getenv("SKYMASTER_REAL_GS_EXECUTORS", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _copilot_scheduler_enabled() -> bool:
    return os.getenv("ENABLE_COPILOT_SCHEDULER", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _trajectory_enabled() -> bool:
    return os.getenv("ENABLE_TRAJECTORY_STORE", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # pylint: disable=unused-argument, too-many-branches
    # Connect to redis
    if not is_fake_enabled():
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    else:
        redis_client = get_redis()

    # Global connection manager for SSE
    # Python < 3.9 doesn't support generic subscription on class
    app.state.conn_manager = ConnectionManager()

    # DB init is done via alembic, no action at startup.
    # SQLite dev mode: swap PG server_defaults for client-side defaults
    from app.sqlite_compat import apply_sqlite_compat
    apply_sqlite_compat()

    # Dev/demo telemetry stack (MAVLink connectors + consumer), enabled with
    # START_TELEMETRY_STACK=true. Drones declare their MAVLink sysid and UDP
    # port in Drone.meta ({"sysid": 1, "udp_port": 14550}); telemetry streams
    # are keyed by Drone UUID so the consumer persists flight_logs rows.
    if os.getenv("START_TELEMETRY_STACK", "false").lower() in ("1", "true", "yes"):
        import asyncio as _aio
        from sqlalchemy import select as _select

        from app.db import AsyncSessionLocal
        from app.models.drone import Drone
        from app.services.mavlink_connector import MavlinkConnector
        from app.services.telemetry_consumer import (
            TelemetryConsumer,
            _build_redis_client,
        )

        _rc = _build_redis_client()
        # WS endpoints (websocket.py) fan out pub/sub via app.state.redis;
        # expose the same client (fake or real) to the app state.
        app.state.redis = _rc
        _consumer = TelemetryConsumer(_rc, session_factory=AsyncSessionLocal)
        _connectors = []
        async with AsyncSessionLocal() as _s:
            _rows = (await _s.execute(_select(Drone))).scalars().all()
            for _d in _rows:
                _meta = getattr(_d, "meta", None) or {}
                _sysid = _meta.get("sysid")
                _port = _meta.get("udp_port")
                if not (_sysid and _port):
                    continue
                _ep = "udpin:0.0.0.0:" + str(_port)
                _conn = MavlinkConnector(
                    _ep, _rc, sysid_map={_sysid: str(_d.id)})
                try:
                    _conn.connect()
                except Exception:  # noqa: BLE001
                    logger.exception("MAVLink connector %s failed", _ep)
                    continue
                _connectors.append(_conn)
        # DJI Cloud API connector (mock by default) — mirrors MAVLink slot:
        # DJI drones declare protocol="dji" and metadata.dji_device_sn; map
        # that SN -> Drone UUID so telemetry lands in the same Redis streams
        # the consumer / WS endpoints already understand (no frontend change).
        _dji_mode = getattr(settings, "dji_mode", "mock")
        if _dji_mode in ("mock", "cloud"):
            from app.services.dji_cloud_connector import DJICloudConnector
            _dji_map: dict[str, str] = {}
            _dji_gateway = getattr(settings, "dji_gateway_sn", "MOCKDOCK001")
            for _d in _rows:
                if getattr(_d, "protocol", "") != "dji":
                    continue
                _dm = getattr(_d, "meta", None) or {}
                _dev_sn = _dm.get("dji_device_sn")
                if not _dev_sn:
                    continue
                _dji_gateway = _dm.get("dji_gateway_sn") or _dji_gateway
                _dji_map[_dev_sn] = str(_d.id)
            if _dji_map:
                _dji = DJICloudConnector(
                    gateway_sn=_dji_gateway,
                    mode=_dji_mode,
                    broker_host=getattr(settings, "dji_broker_host", "127.0.0.1"),
                    broker_port=getattr(settings, "dji_broker_port", 1883),
                    client_id=getattr(settings, "dji_client_id", "") or None,
                    username=getattr(settings, "dji_username", "") or None,
                    password=getattr(settings, "dji_password", "") or None,
                    redis_client=_rc,
                    drone_id_map=_dji_map,
                    mock_start_lat=getattr(settings, "dji_mock_start_lat", 22.8167),
                    mock_start_lng=getattr(settings, "dji_mock_start_lng", 108.3167),
                    mock_drones=len(_dji_map),
                    calibration_config_path=getattr(
                        settings, "dji_calibration_config", "") or None,
                    rc_calibration_path=getattr(
                        settings, "dji_rc_calibration_file", "") or None,
                    control_config_path=getattr(
                        settings, "dji_control_config", "") or None,
                    mission_config_path=getattr(
                        settings, "dji_mission_config", "") or None,
                    mission_routes_path=getattr(
                        settings, "dji_mission_routes", "") or None,
                )
                try:
                    _dji.connect()
                    app.state.dji_connector = _dji
                    _connectors.append(_dji)
                    logger.info(
                        "DJI connector started: mode=%s gateway=%s drones=%d",
                        _dji_mode, _dji_gateway, len(_dji_map))
                except Exception:  # noqa: BLE001
                    logger.exception("DJI connector failed to start")

        if _connectors:
            _tasks = [_aio.create_task(_c.run()) for _c in _connectors]
            _tasks.append(_aio.create_task(_consumer.run()))
            app.state.telemetry_stack_tasks = _tasks
            app.state.telemetry_stack = (_connectors, _consumer)
            logger.info(
                "Telemetry stack started: %d connector(s) + consumer",
                len(_connectors))

    # Start periodic revoked JWT cleanup task if enabled
    revoke_cleanup_task: asyncio.Task | None = None
    from app.services.auth import jwt
    async def _revoke_cleanup_loop() -> None:
        interval_h = 6
        while True:
            try:
                await jwt.cleanup_expired_revocations()
            except Exception as exc:  # noqa: BLE001
                logger.warning("revoked_token cleanup failed: %s", exc)
            await asyncio.sleep(interval_h * 3600)

    if bool(os.getenv("RUN_REVOKED_CLEANUP", "true")):
        revoke_cleanup_task = asyncio.create_task(
            _revoke_cleanup_loop(), name="revoked-token-cleanup",
        )
        logger.info("RevokedToken cleanup task started (every 6h)")

    # Initialize 3DGS/4DGS real executors (if enabled)
    if _real_gs_executors_enabled():
        from app.services import scene_pipeline
        from app.services.scene_executors import GsplatExecutor, Gsplat4DExecutor

        if os.getenv("SKYMASTER_SCENE_KIND_DEFAULT", "3dgs") == "4dgs":
            scene_pipeline.set_executor(Gsplat4DExecutor())
            logger.info("Using real 4DGS executor (Gsplat4D)")
        else:
            scene_pipeline.set_executor(GsplatExecutor())
            logger.info("Using real 3DGS executor (COLMAP + Gsplat)")
    else:
        logger.info("Using NoOpExecutor for 3DGS (dev/test mode)")

    # T12.2: Copilot workflow scheduler background task.
    scheduler_task: asyncio.Task | None = None
    scheduler_stop: asyncio.Event | None = None
    if _copilot_scheduler_enabled():
        from app.db import AsyncSessionLocal
        from app.services.workflow_scheduler import (
            TICK_INTERVAL_SECONDS, run_forever,
        )

        interval = float(
            os.getenv("COPILOT_SCHEDULER_INTERVAL_S", str(TICK_INTERVAL_SECONDS)),
        )
        scheduler_stop = asyncio.Event()
        scheduler_task = asyncio.create_task(
            run_forever(
                session_factory=AsyncSessionLocal,
                interval_seconds=interval,
                stop_event=scheduler_stop,
            ),
            name="copilot-workflow-scheduler",
        )
        logger.info("Copilot workflow scheduler background task started")

    # Finished startup
    logger.info("SkyMaster backend starting up — version v2.1-dev")
    yield

    # Telemetry stack teardown (started above when
    # START_TELEMETRY_STACK=true)
    _stack = getattr(app.state, "telemetry_stack", None)
    if _stack:
        _conns, _cons = _stack
        for _c in _conns:
            _c.stop()
        _cons.stop()
        for _t in getattr(app.state, "telemetry_stack_tasks", []):
            _t.cancel()
        logger.info("Telemetry stack stopped")

    # Shutdown: cancel background tasks
    if revoke_cleanup_task is not None:
        revoke_cleanup_task.cancel()
    if scheduler_task is not None and scheduler_stop is not None:
        scheduler_stop.set()
        await scheduler_task
    if not is_fake_enabled():
        await redis_client.close()

    # Dispose sqlalchemy engine
    await engine.dispose()
    logger.info("SkyMaster backend shutdown complete")


def build_app() -> FastAPI:
    application = FastAPI(
        title="SkyMaster Drone Control Platform",
        description="Open-source multi-protocol drone management platform",
        version="v2.1-draft",
        lifespan=lifespan,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    # Set up CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include v1 API
    application.include_router(api_router, prefix="/api/v1")

    # Health check root
    @application.get("/health")
    async def health_check() -> dict[str, str | bool]:
        return {"status": "ok", "ready": True}

    return application


app = build_app()
