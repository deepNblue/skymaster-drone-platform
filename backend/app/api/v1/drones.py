"""Drone endpoints — list / create (idempotent) / detail."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models.drone import Drone
from app.models.user import User
from app.schemas.drone import DroneCreate, DroneOut

router = APIRouter(prefix="/drones", tags=["drones"])


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
