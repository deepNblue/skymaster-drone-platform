"""F4.1 · Copilot v2 turn feedback REST."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.copilot_feedback import (
    FeedbackError, clear_feedback, get_my_feedback, intent_scoreboard,
    recent_negative, submit_feedback, turn_stats,
)


router = APIRouter(
    prefix="/copilot/feedback", tags=["copilot-feedback"],
)


class FeedbackIn(BaseModel):
    rating: str = Field(..., description="up | down")
    comment: str | None = Field(None, max_length=2000)


def _map(exc: FeedbackError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


@router.post("/turns/{turn_id}", status_code=201)
async def api_submit(
    turn_id: UUID,
    body: FeedbackIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await submit_feedback(
            db, turn_id=turn_id, user_id=user.id,
            rating=body.rating, comment=body.comment,
        )
    except FeedbackError as e:
        raise _map(e)


@router.delete("/turns/{turn_id}", status_code=204)
async def api_clear(
    turn_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await clear_feedback(db, turn_id=turn_id, user_id=user.id)


@router.get("/turns/{turn_id}/me")
async def api_my(
    turn_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    fb = await get_my_feedback(
        db, turn_id=turn_id, user_id=user.id,
    )
    return fb or {"turn_id": str(turn_id), "rating": None}


@router.get("/turns/{turn_id}/stats")
async def api_turn_stats(
    turn_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, int | float]:
    return await turn_stats(db, turn_id=turn_id)


@router.get("/recent-negative")
async def api_recent_negative(
    limit: int = Query(20, ge=1, le=200),
    intent: str | None = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await recent_negative(db, limit=limit, intent=intent)


@router.get("/intent-scoreboard")
async def api_intent_scoreboard(
    min_total: int = Query(3, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await intent_scoreboard(db, min_total=min_total)
