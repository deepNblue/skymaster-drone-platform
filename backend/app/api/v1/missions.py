"""Mission endpoints — list / create / validate / dispatch / abort / logs."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.drone import Drone
from app.models.flight_log import FlightLog
from app.models.mission import Mission
from app.models.user import User
from app.schemas.mission import MissionCreate, MissionOut
from app.services.connection_manager import ConnectionManager
from app.services.mission_dispatcher import MissionDispatcher

router = APIRouter(prefix="/missions", tags=["missions"])


async def _load_mission(
    db: AsyncSession, mission_id: UUID, org_id: UUID | None
) -> Mission:
    result = await db.execute(
        select(Mission).where(
            Mission.id == mission_id, Mission.org_id == org_id
        )
    )
    mission = result.scalar_one_or_none()
    if mission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found"
        )
    return mission


def _drone_endpoint(drone: Drone) -> str:
    """Resolve the MAVLink endpoint for a drone.

    Priority: drone.meta['mavlink_endpoint'] -> env MAVLINK_ENDPOINT ->
    default udpin:0.0.0.0:14550.
    """
    meta = drone.meta or {}
    endpoint = meta.get("mavlink_endpoint")
    if endpoint:
        return str(endpoint)
    return os.getenv("MAVLINK_ENDPOINT", "udpin:0.0.0.0:14550")


@router.get("", response_model=dict)
async def list_missions(
    status_filter: str | None = Query(default=None, alias="status"),
    drone_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    stmt = select(Mission).where(Mission.org_id == user.org_id)
    if status_filter:
        stmt = stmt.where(Mission.status == status_filter)
    if drone_id:
        stmt = stmt.where(Mission.drone_id == drone_id)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    stmt = (
        stmt.order_by(Mission.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [MissionOut.model_validate(r).model_dump() for r in rows],
    }


@router.post("", response_model=MissionOut, status_code=status.HTTP_201_CREATED)
async def create_mission(
    payload: MissionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MissionOut:
    mission = Mission(
        org_id=user.org_id,
        drone_id=payload.drone_id,
        name=payload.name,
        template=payload.template,
        waypoints=[wp.model_dump() for wp in payload.waypoints],
        params=payload.params,
        status="draft",
        created_by=user.id,
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)
    return MissionOut.model_validate(mission)


@router.get("/{mission_id}", response_model=MissionOut)
async def get_mission(
    mission_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MissionOut:
    mission = await _load_mission(db, mission_id, user.org_id)
    return MissionOut.model_validate(mission)


@router.post("/{mission_id}/validate")
async def validate_mission_endpoint(
    mission_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Run pre-flight validation on a mission without changing state."""
    mission = await _load_mission(db, mission_id, user.org_id)
    dispatcher = MissionDispatcher()
    result = await dispatcher.validate_mission(mission)
    return result.to_dict()


@router.post("/{mission_id}/dispatch")
async def dispatch_mission_endpoint(
    mission_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Validate + upload to drone + start.

    Returns ``{mission_id, status, mavlink_ack}`` on success; raises 400 on
    validation failure or 502 on dispatch failure.
    """
    mission = await _load_mission(db, mission_id, user.org_id)
    if mission.drone_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mission has no assigned drone",
        )

    dispatcher = MissionDispatcher()
    validation = await dispatcher.validate_mission(mission)
    if not validation.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"validation": validation.to_dict()},
        )

    drone = (
        await db.execute(select(Drone).where(Drone.id == mission.drone_id))
    ).scalar_one_or_none()
    if drone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="assigned drone not found",
        )

    manager = ConnectionManager.instance()
    connector = await manager.get_or_create(
        drone_id=drone.id, endpoint=_drone_endpoint(drone)
    )

    result = await dispatcher.dispatch_to_drone(mission, connector._conn)

    if result["status"] != "dispatched":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "mission_id": str(mission.id),
                "status": "failed",
                "mavlink_ack": result.get("mavlink_ack"),
                "error": result.get("error"),
            },
        )

    mission.status = "dispatched"
    mission.dispatched_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "mission_id": str(mission.id),
        "status": mission.status,
        "mavlink_ack": result.get("mavlink_ack"),
    }


@router.post("/{mission_id}/abort")
async def abort_mission_endpoint(
    mission_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    mission = await _load_mission(db, mission_id, user.org_id)
    if mission.drone_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mission has no assigned drone",
        )

    manager = ConnectionManager.instance()
    connector = manager.get(mission.drone_id)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no active MAVLink connection for drone; cannot abort",
        )

    dispatcher = MissionDispatcher()
    result = await dispatcher.abort(connector._conn)

    if result["status"] != "aborted":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": result.get("error")},
        )

    mission.status = "aborted"
    mission.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return {"mission_id": str(mission.id), "status": mission.status}


@router.get("/{mission_id}/logs")
async def get_mission_logs(
    mission_id: UUID,
    limit: int = Query(default=1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return the latest telemetry rows for a mission (newest first)."""
    # Verify tenancy first.
    await _load_mission(db, mission_id, user.org_id)

    stmt = (
        select(FlightLog)
        .where(FlightLog.mission_id == mission_id)
        .order_by(FlightLog.time.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "time": r.time.isoformat() if r.time else None,
            "drone_id": str(r.drone_id) if r.drone_id else None,
            "mission_id": str(r.mission_id) if r.mission_id else None,
            "lat": r.lat,
            "lng": r.lng,
            "alt": r.alt,
            "speed": r.speed,
            "heading": r.heading,
            "roll": r.roll,
            "pitch": r.pitch,
            "yaw": r.yaw,
            "battery_pct": r.battery_pct,
            "rssi": r.rssi,
            "gps_sats": r.gps_sats,
            "flight_mode": r.flight_mode,
        }
        for r in rows
    ]
    return {"mission_id": str(mission_id), "count": len(items), "items": items}
