"""Admin endpoints for reading login history and anomalies."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.login_event import LoginEvent
from app.models.user import User

router = APIRouter(prefix="/auth/login-events", tags=["auth-events"])


class LoginEventOut(BaseModel):
    id: UUID
    user_id: Optional[UUID]
    email: Optional[str]
    method: str
    outcome: str
    ip: Optional[str]
    country: Optional[str]
    user_agent: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) != "admin":
        raise HTTPException(403, "Admin role required")


@router.get("/me", response_model=list[LoginEventOut])
async def my_login_history(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LoginEventOut]:
    """A regular user can view their own recent login history."""
    rows = (await db.execute(
        select(LoginEvent)
        .where(LoginEvent.user_id == user.id)
        .order_by(desc(LoginEvent.created_at))
        .limit(limit)
    )).scalars().all()
    return [LoginEventOut.model_validate(r) for r in rows]


@router.get("", response_model=list[LoginEventOut])
async def list_login_events(
    outcome: Optional[str] = None,
    email: Optional[str] = None,
    ip: Optional[str] = None,
    since_hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LoginEventOut]:
    """Admin — global login-event browse."""
    _require_admin(user)
    since = datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)
    stmt = select(LoginEvent).where(LoginEvent.created_at >= since)
    if outcome:
        stmt = stmt.where(LoginEvent.outcome == outcome)
    if email:
        stmt = stmt.where(LoginEvent.email == email)
    if ip:
        stmt = stmt.where(LoginEvent.ip == ip)
    stmt = stmt.order_by(desc(LoginEvent.created_at)).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [LoginEventOut.model_validate(r) for r in rows]


class LoginEventStats(BaseModel):
    total: int
    success: int
    failed: int
    by_outcome: dict[str, int]


@router.get("/stats", response_model=LoginEventStats)
async def login_stats(
    since_hours: int = Query(24, ge=1, le=720),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoginEventStats:
    """Admin — aggregate stats for the login dashboard."""
    _require_admin(user)
    since = datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)
    rows = (await db.execute(
        select(LoginEvent.outcome, func.count(LoginEvent.id))
        .where(LoginEvent.created_at >= since)
        .group_by(LoginEvent.outcome)
    )).all()
    by = {outcome: int(cnt) for outcome, cnt in rows}
    return LoginEventStats(
        total=sum(by.values()),
        success=by.get("success", 0),
        failed=sum(v for k, v in by.items() if k != "success"),
        by_outcome=by,
    )
