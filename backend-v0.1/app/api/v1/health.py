"""Health check endpoints — /health, /livez, /readyz.

* `/health` — legacy detailed status (kept for backward compat).
* `/livez`  — liveness probe: is the process up? Never touches downstreams.
* `/readyz` — readiness probe: are DB + Redis reachable? Fails 503 if not.

Kubernetes / systemd probes should use `/livez` + `/readyz`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["health"])


async def _db_ping(db: AsyncSession) -> tuple[str, bool]:
    try:
        await db.execute(text("SELECT 1"))
        return "ok", True
    except Exception as exc:  # pragma: no cover
        return f"error: {exc.__class__.__name__}", False


async def _redis_ping(request: Request) -> tuple[str, bool]:
    try:
        redis = request.app.state.redis
        pong = await redis.ping()
        if not pong:
            return "error: no pong", False
        return "ok", True
    except Exception as exc:  # pragma: no cover
        return f"error: {exc.__class__.__name__}", False


@router.get("/health")
async def health(
    request: Request, db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Return detailed liveness/readiness (legacy endpoint)."""
    db_status, db_ok = await _db_ping(db)
    redis_status, redis_ok = await _redis_ping(request)
    overall = "ok" if db_ok and redis_ok else "degraded"
    return {"status": overall, "db": db_status, "redis": redis_status}


@router.get("/livez")
async def livez() -> dict[str, str]:
    """Liveness probe — always 200 while process is up.

    Do NOT touch downstream services here; that's readiness territory.
    Restarting on a DB blip is worse than degraded reads.
    """
    return {"status": "alive"}


@router.get("/readyz")
async def readyz(
    request: Request, db: AsyncSession = Depends(get_db),
):
    """Readiness probe — 200 iff DB + Redis are both reachable, else 503.

    Meant for load-balancer removal on transient dependency failures.
    """
    db_status, db_ok = await _db_ping(db)
    redis_status, redis_ok = await _redis_ping(request)
    if db_ok and redis_ok:
        return {"status": "ready", "db": db_status, "redis": redis_status}
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"status": "not_ready", "db": db_status, "redis": redis_status},
    )

