"""F3.4 · Community notification REST — unified social inbox."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.community_notification import (
    list_for_user, mark_all_read, mark_read, unread_count,
    unread_summary,
)


router = APIRouter(
    prefix="/community/notifications", tags=["community-notifications"],
)


@router.get("")
async def api_list(
    only_unread: bool = Query(False),
    kinds: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await list_for_user(
        db, user_id=user.id,
        only_unread=only_unread, kinds=kinds,
        limit=limit, offset=offset,
    )


@router.get("/unread-count")
async def api_unread_count(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    total = await unread_count(db, user_id=user.id)
    return {"unread": total}


@router.get("/unread-summary")
async def api_unread_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    return await unread_summary(db, user_id=user.id)


@router.post("/{notification_id}/read", status_code=200)
async def api_mark_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ok = await mark_read(
        db, user_id=user.id, notification_id=notification_id,
    )
    if not ok:
        raise HTTPException(404, "notification not found or already read")
    return {"id": str(notification_id), "read": True}


@router.post("/read-all", status_code=200)
async def api_mark_all_read(
    kinds: list[str] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    n = await mark_all_read(db, user_id=user.id, kinds=kinds)
    return {"updated": n}
