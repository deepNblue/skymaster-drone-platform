"""Geo-Fence REST API — v2.0 compliance track."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.geofence import get_geofence

router = APIRouter(prefix="/geofence", tags=["geofence", "compliance"])


class WaypointIn(BaseModel):
    lat: float
    lng: float
    alt: float = 100.0


class CheckBody(BaseModel):
    waypoints: list[WaypointIn] = Field(..., min_length=1)


@router.get("/zones")
async def list_zones() -> dict:
    engine = get_geofence()
    zones = [
        {
            "id": z.id,
            "name": z.name,
            "kind": z.kind,
            "polygon": z.polygon,
            "max_alt_m": z.max_alt_m,
            "source": z.source,
        }
        for z in engine.all_zones()
    ]
    return {"count": len(zones), "zones": zones}


@router.post("/check")
async def check_waypoints(body: CheckBody) -> dict:
    engine = get_geofence()
    result = engine.check_waypoints([wp.model_dump() for wp in body.waypoints])
    return result.to_dict()
