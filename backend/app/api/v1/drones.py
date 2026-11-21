"""Drone endpoints — list / create (idempotent) / detail."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models.drone import Drone
from app.models.user import User
from app.schemas.drone import DroneCreate, DroneOut

router = APIRouter(prefix="/drones", tags=["drones"])


@router.get("/stats", response_model=dict)
async def drone_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregated dashboard stats (online drones, missions today, pending
    approvals, flight log counts) for the landing dashboard cards."""
    from datetime import datetime, timedelta, timezone

    from app.models.flight_approval import FlightApproval
    from app.models.flight_log import FlightLog
    from app.models.mission import Mission

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    active_since = now - timedelta(minutes=5)

    drones = (await db.execute(select(Drone))).scalars().all()
    total = len(drones)

    # flight log aggregates
    logs_24h = (await db.execute(
        select(func.count()).select_from(FlightLog).where(
            FlightLog.time >= now - timedelta(hours=24)))).scalar() or 0
    per_drone_rows = (await db.execute(
        select(FlightLog.drone_id, func.count().label("c"))
        .where(FlightLog.time >= active_since)
        .group_by(FlightLog.drone_id))).all()
    active_ids = {str(r[0]) for r in per_drone_rows}

    # hourly telemetry volume for the last 24h (cross-dialect: SQLite
    # substr on ISO text works; PG uses to_char)
    dialect_name = ""
    if db.bind is not None:
        dialect_name = str(getattr(db.bind.dialect, "name", ""))
    try:
        if "sqlite" in dialect_name:
            hour_expr = func.substr(cast(FlightLog.time, String), 1, 13)
        else:
            hour_expr = func.to_char(FlightLog.time, 'YYYY-MM-DD HH24')
        hour_rows = (await db.execute(
            select(hour_expr.label("h"), func.count().label("c"))
            .where(FlightLog.time >= now - timedelta(hours=24))
            .group_by(hour_expr).order_by(hour_expr))).all()
    except Exception:
        hour_rows = []
    hourly = [{"hour": str(r[0]), "count": int(r[1])} for r in hour_rows]

    missions_today = (await db.execute(
        select(func.count()).select_from(Mission).where(
            Mission.org_id == user.org_id,
            Mission.created_at >= day_start))).scalar() or 0

    pending_approvals = (await db.execute(
        select(func.count()).select_from(FlightApproval).where(
            FlightApproval.tenant_id == user.org_id,
            FlightApproval.status == "pending"))).scalar() or 0

    status_dist: dict[str, int] = {}
    for d in drones:
        s = d.status or "unknown"
        status_dist[s] = status_dist.get(s, 0) + 1

    per_drone = [
        {
            "drone_id": str(d.id),
            "sn": d.sn,
            "online": str(d.id) in active_ids,
        }
        for d in drones
    ]
    return {
        "total_drones": total,
        "online_drones": len(active_ids),
        "flight_logs_24h": logs_24h,
        "hourly": hourly,
        "missions_today": missions_today,
        "pending_approvals": pending_approvals,
        "status_dist": status_dist,
        "per_drone": per_drone,
    }


@router.get("/{drone_id}/track")
async def drone_track(
    drone_id: UUID,
    seconds: int = Query(300, ge=60, le=86400),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Downsampled historical track for one drone from flight_logs.

    Sampled at ~1 point per minute to keep payloads small (24h -> ~1440 pts).
    """
    from datetime import datetime, timedelta, timezone

    from app.models.flight_log import FlightLog

    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=seconds)

    dialect_name = ""
    if db.bind is not None:
        dialect_name = str(getattr(db.bind.dialect, "name", ""))
    if "sqlite" in dialect_name:
        minute_expr = func.substr(cast(FlightLog.time, String), 1, 16)
    else:
        minute_expr = func.to_char(FlightLog.time, 'YYYY-MM-DD HH24:MI')

    try:
        rn = func.row_number().over(
            partition_by=minute_expr, order_by=FlightLog.time.desc()
        ).label("rn")
        sub = (
            select(FlightLog.time, FlightLog.lat, FlightLog.lng, FlightLog.alt, rn)
            .where(
                FlightLog.drone_id == drone_id,
                FlightLog.time >= since,
                FlightLog.lat.is_not(None),
                FlightLog.lng.is_not(None),
            )
            .subquery()
        )
        rows = (await db.execute(
            select(sub.c.time, sub.c.lat, sub.c.lng, sub.c.alt)
            .where(sub.c.rn == 1)
            .order_by(sub.c.time))).all()
    except Exception:
        # group_by on expression not supported by dialect -> raw cap
        rows = (await db.execute(
            select(FlightLog.time, FlightLog.lat, FlightLog.lng, FlightLog.alt)
            .where(
                FlightLog.drone_id == drone_id,
                FlightLog.time >= since,
                FlightLog.lat.is_not(None),
            )
            .order_by(FlightLog.time).limit(2000))).all()

    trail = [
        {
            "lat": float(r[1]),
            "lng": float(r[2]),
            "alt": float(r[3]) if r[3] is not None else 100.0,
            "ts": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
        }
        for r in rows
    ]
    latest_ts = trail[-1]["ts"] if trail else None
    return {"trail": trail, "points": len(trail), "seconds": seconds, "latest_ts": latest_ts}


@router.get("", response_model=dict)
async def list_drones(
    status_filter: str | None = Query(default=None, alias="status"),
    protocol: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    stmt = select(Drone).where(Drone.org_id == user.org_id)
    if status_filter:
        stmt = stmt.where(Drone.status == status_filter)
    if protocol:
        stmt = stmt.where(Drone.protocol == protocol)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Drone.sn.ilike(like), Drone.model.ilike(like)))

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    stmt = (
        stmt.order_by(Drone.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [DroneOut.model_validate(r).model_dump(by_alias=True) for r in rows],
    }


@router.post(
    "",
    response_model=DroneOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_drone(
    payload: DroneCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "operator")),
) -> DroneOut:
    """Register a drone. Idempotent by `sn` — returns existing row if present."""
    existing = (
        await db.execute(select(Drone).where(Drone.sn == payload.sn))
    ).scalar_one_or_none()
    if existing is not None:
        return DroneOut.model_validate(existing)

    drone = Drone(
        org_id=user.org_id,
        sn=payload.sn,
        model=payload.model,
        protocol=payload.protocol,
        meta=payload.metadata,
    )
    db.add(drone)
    await db.commit()
    await db.refresh(drone)
    return DroneOut.model_validate(drone)


@router.get("/{drone_id}", response_model=DroneOut)
async def get_drone(
    drone_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DroneOut:
    result = await db.execute(
        select(Drone).where(Drone.id == drone_id, Drone.org_id == user.org_id)
    )
    drone = result.scalar_one_or_none()
    if drone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drone not found")
    return DroneOut.model_validate(drone)
