"""Approval-as-a-Service REST API — R21 Step E.

Admin CRUD for subscriber clients + fan-out test-fire endpoint + retry
sweep. Authority (partner) side simply POSTs are received on the
``callback_url`` they registered — the platform never *ingests* — so
this router is purely admin-facing.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.aaas import AaasClient, AaasDelivery
from app.models.flight_approval import FlightApproval
from app.models.user import User
from app.services.aaas import (
    APPROVAL_EVENTS, fanout_approval_event, new_client_secret,
    retry_due_deliveries,
)
from app.deps import get_current_user

router = APIRouter(prefix="/aaas", tags=["aaas"])


def _require_admin(user: User) -> None:
    role = getattr(user, "role", None)
    if role != "admin":
        raise HTTPException(status_code=403, detail="admin only")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: Optional[str] = None
    callback_url: AnyHttpUrl
    events: Optional[list[str]] = None
    active: bool = True


class ClientOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    callback_url: str
    secret: str
    events: Optional[list[str]] = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DeliveryOut(BaseModel):
    id: UUID
    client_id: UUID
    event: str
    event_id: UUID
    approval_id: Optional[UUID] = None
    status: str
    attempts: int
    last_status_code: Optional[int] = None
    last_attempt_at: Optional[datetime] = None
    next_attempt_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RotateOut(BaseModel):
    id: UUID
    secret: str


# ---------------------------------------------------------------------------
# Meta endpoints
# ---------------------------------------------------------------------------


@router.get("/events/catalog")
async def list_event_catalog(user: User = Depends(get_current_user)) -> dict:
    """Public within the platform — used by admin UI to populate checkbox
    list of subscribable events."""
    return {"events": list(APPROVAL_EVENTS)}


# ---------------------------------------------------------------------------
# Client CRUD
# ---------------------------------------------------------------------------


@router.post("/clients", response_model=ClientOut, status_code=201)
async def create_client(
    body: ClientIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AaasClient:
    _require_admin(user)
    _validate_events(body.events)
    row = AaasClient(
        name=body.name,
        description=body.description,
        callback_url=str(body.callback_url),
        secret=new_client_secret(),
        events=body.events,
        active=body.active,
        created_by=user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/clients", response_model=list[ClientOut])
async def list_clients(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(False),
) -> list[AaasClient]:
    _require_admin(user)
    q = select(AaasClient).order_by(AaasClient.created_at.desc())
    if active_only:
        q = q.where(AaasClient.active.is_(True))
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/clients/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AaasClient:
    _require_admin(user)
    row = await db.get(AaasClient, client_id)
    if row is None:
        raise HTTPException(404, "client not found")
    return row


@router.patch("/clients/{client_id}", response_model=ClientOut)
async def patch_client(
    client_id: UUID,
    body: ClientIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AaasClient:
    _require_admin(user)
    _validate_events(body.events)
    row = await db.get(AaasClient, client_id)
    if row is None:
        raise HTTPException(404, "client not found")
    row.name = body.name
    row.description = body.description
    row.callback_url = str(body.callback_url)
    row.events = body.events
    row.active = body.active
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/clients/{client_id}/rotate-secret", response_model=RotateOut)
async def rotate_secret(
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RotateOut:
    _require_admin(user)
    row = await db.get(AaasClient, client_id)
    if row is None:
        raise HTTPException(404, "client not found")
    row.secret = new_client_secret()
    await db.commit()
    return RotateOut(id=row.id, secret=row.secret)


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=None)
async def delete_client(
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    row = await db.get(AaasClient, client_id)
    if row is None:
        raise HTTPException(404, "client not found")
    await db.delete(row)
    await db.commit()
    from fastapi import Response
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Deliveries + admin ops
# ---------------------------------------------------------------------------


@router.get("/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    client_id: Optional[UUID] = None,
    approval_id: Optional[UUID] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, le=500),
) -> list[AaasDelivery]:
    _require_admin(user)
    q = select(AaasDelivery).order_by(AaasDelivery.created_at.desc()).limit(limit)
    if client_id:
        q = q.where(AaasDelivery.client_id == client_id)
    if approval_id:
        q = q.where(AaasDelivery.approval_id == approval_id)
    if status_filter:
        q = q.where(AaasDelivery.status == status_filter)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/stats")
async def delivery_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_admin(user)
    q = select(AaasDelivery.status, func.count()).group_by(AaasDelivery.status)
    result = await db.execute(q)
    return {"by_status": {s: int(n) for s, n in result.all()}}


@router.post("/retry-sweep")
async def retry_sweep(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, le=500),
) -> dict:
    """Admin-triggered retry of due deliveries (manual replacement for cron)."""
    _require_admin(user)
    summary = await retry_due_deliveries(db, limit=limit)
    await db.commit()
    return summary


@router.post("/test-fire/{approval_id}")
async def test_fire(
    approval_id: UUID,
    event: str = Query(..., description="Approval lifecycle event to fan out"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually re-fan-out an event for an existing approval. Useful for
    verifying a new subscriber's callback endpoint end-to-end."""
    _require_admin(user)
    if event not in APPROVAL_EVENTS:
        raise HTTPException(400, f"unknown event; try one of {list(APPROVAL_EVENTS)}")
    approval = await db.get(FlightApproval, approval_id)
    if approval is None:
        raise HTTPException(404, "approval not found")
    delivery_ids = await fanout_approval_event(db, event=event, approval=approval)
    await db.commit()
    return {"delivered_to": len(delivery_ids), "delivery_ids": [str(x) for x in delivery_ids]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_events(events: list[str] | None) -> None:
    if not events:
        return
    unknown = [e for e in events if e not in APPROVAL_EVENTS]
    if unknown:
        raise HTTPException(
            400,
            f"unknown events: {unknown}; valid: {list(APPROVAL_EVENTS)}",
        )
