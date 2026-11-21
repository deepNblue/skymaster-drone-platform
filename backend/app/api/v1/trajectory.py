"""Trajectory API — return historical flight paths from the local SQLite store.

Endpoints:
    GET /api/v1/trajectory/drones                  → list drone_ids w/ data
    GET /api/v1/trajectory/{drone_id}?seconds=300  → last 5min trail (default)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/trajectory", tags=["trajectory"])


def _store(request: Request):
    store = getattr(request.app.state, "trajectory_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="trajectory store disabled (set ENABLE_TRAJECTORY_STORE=true)",
        )
    return store


@router.get("/drones")
async def list_drones(request: Request) -> dict[str, Any]:
    store = _store(request)
    drones = await store.get_drones()
    return {"drones": drones}


@router.get("/{drone_id}")
async def get_trail(
    request: Request,
    drone_id: str,
    seconds: float = Query(300.0, ge=1, le=86400, description="Time window (seconds)"),
    limit: int = Query(2000, ge=1, le=10000),
) -> dict[str, Any]:
    store = _store(request)
    trail = await store.get_trail(drone_id, seconds=seconds, limit=limit)
    return {
        "drone_id": drone_id,
        "seconds": seconds,
        "count": len(trail),
        "trail": trail,
    }
