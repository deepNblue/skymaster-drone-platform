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
