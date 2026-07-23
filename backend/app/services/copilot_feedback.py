"""F4.1 · Copilot v2 turn feedback service.

Upsert-style feedback with rating (up/down) and optional comment,
plus aggregate stats for improvement analytics.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_turn_feedback import (
    RATING_DOWN, RATING_UP, VALID_RATINGS, CopilotTurnFeedback,
)
from app.models.vision_copilot import CopilotTurnV2


class FeedbackError(Exception):
    pass


# ------------------------- Upsert -------------------------

async def submit_feedback(
    db: AsyncSession, *,
    turn_id: uuid.UUID,
    user_id: uuid.UUID,
    rating: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """Upsert feedback: same (turn, user) → update rating/comment."""
    if rating not in VALID_RATINGS:
        raise FeedbackError(
            f"invalid rating: {rating}; expected up|down",
        )
    if comment is not None and len(comment) > 2000:
        raise FeedbackError("comment too long (>2000 chars)")
    # Verify turn exists.
    turn = await db.get(CopilotTurnV2, turn_id)
    if turn is None:
        raise FeedbackError("turn not found")

    q = select(CopilotTurnFeedback).where(
        CopilotTurnFeedback.turn_id == turn_id,
        CopilotTurnFeedback.user_id == user_id,
    )
    existing = (await db.execute(q)).scalar_one_or_none()
    if existing is not None:
        existing.rating = rating
        existing.comment = comment
        await db.commit()
        await db.refresh(existing)
        return _serialize(existing, updated=True)

    fb = CopilotTurnFeedback(
        turn_id=turn_id, user_id=user_id,
        rating=rating, comment=comment,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return _serialize(fb, updated=False)


async def clear_feedback(
    db: AsyncSession, *, turn_id: uuid.UUID, user_id: uuid.UUID,
) -> bool:
    q = select(CopilotTurnFeedback).where(
        CopilotTurnFeedback.turn_id == turn_id,
        CopilotTurnFeedback.user_id == user_id,
    )
    fb = (await db.execute(q)).scalar_one_or_none()
    if fb is None:
        return False
    await db.delete(fb)
    await db.commit()
    return True


# ------------------------- Read -------------------------

async def get_my_feedback(
    db: AsyncSession, *, turn_id: uuid.UUID, user_id: uuid.UUID,
) -> dict[str, Any] | None:
    q = select(CopilotTurnFeedback).where(
        CopilotTurnFeedback.turn_id == turn_id,
        CopilotTurnFeedback.user_id == user_id,
    )
    fb = (await db.execute(q)).scalar_one_or_none()
    return _serialize(fb, updated=False) if fb else None


async def turn_stats(
    db: AsyncSession, *, turn_id: uuid.UUID,
) -> dict[str, int | float]:
    """Aggregate up/down counts + score for a single turn."""
    q = select(
        func.count().label("total"),
        func.sum(
            case((CopilotTurnFeedback.rating == RATING_UP, 1), else_=0),
        ).label("up"),
        func.sum(
            case(
                (CopilotTurnFeedback.rating == RATING_DOWN, 1),
                else_=0,
            ),
        ).label("down"),
    ).where(CopilotTurnFeedback.turn_id == turn_id)
    row = (await db.execute(q)).one()
    up = int(row.up or 0)
    down = int(row.down or 0)
    total = int(row.total or 0)
    score = (up - down) / total if total > 0 else 0.0
    return {"total": total, "up": up, "down": down, "score": score}


async def recent_negative(
    db: AsyncSession, *, limit: int = 20,
    intent: str | None = None,
) -> list[dict[str, Any]]:
    """Newest 'down' feedback for improvement review.

    Joins turn to surface user_text + intent for triage.
    """
    q = (
        select(CopilotTurnFeedback, CopilotTurnV2)
        .join(
            CopilotTurnV2,
            CopilotTurnV2.id == CopilotTurnFeedback.turn_id,
        )
        .where(CopilotTurnFeedback.rating == RATING_DOWN)
        .order_by(CopilotTurnFeedback.created_at.desc())
        .limit(min(limit, 200))
    )
    if intent:
        q = q.where(CopilotTurnV2.intent == intent)
    rows = (await db.execute(q)).all()
    out: list[dict[str, Any]] = []
    for fb, turn in rows:
        ca = fb.created_at
        if ca is not None and ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        out.append({
            "feedback_id": str(fb.id),
            "turn_id": str(turn.id),
            "session_id": str(turn.session_id),
            "intent": turn.intent,
            "user_text": turn.user_text,
            "reply_text": turn.reply_text,
            "comment": fb.comment,
            "created_at": ca.isoformat() if ca else None,
        })
    return out


async def intent_scoreboard(
    db: AsyncSession, *,
    min_total: int = 3,
) -> list[dict[str, Any]]:
    """Per-intent aggregate score, sorted worst first.

    Only includes intents with >= min_total feedback entries.
    """
    q = (
        select(
            CopilotTurnV2.intent.label("intent"),
            func.count().label("total"),
            func.sum(
                case(
                    (CopilotTurnFeedback.rating == RATING_UP, 1),
                    else_=0,
                ),
            ).label("up"),
            func.sum(
                case(
                    (CopilotTurnFeedback.rating == RATING_DOWN, 1),
                    else_=0,
                ),
            ).label("down"),
        )
        .join(
            CopilotTurnV2,
            CopilotTurnV2.id == CopilotTurnFeedback.turn_id,
        )
        .group_by(CopilotTurnV2.intent)
        .having(func.count() >= min_total)
    )
    rows = (await db.execute(q)).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        total = int(r.total or 0)
        up = int(r.up or 0)
        down = int(r.down or 0)
        score = (up - down) / total if total > 0 else 0.0
        out.append({
            "intent": r.intent or "(none)",
            "total": total, "up": up, "down": down,
            "score": round(score, 4),
        })
    # Worst first (lowest score, then highest volume).
    out.sort(key=lambda x: (x["score"], -x["total"]))
    return out


# ------------------------- helpers -------------------------

def _serialize(
    fb: CopilotTurnFeedback, *, updated: bool,
) -> dict[str, Any]:
    ca = fb.created_at
    if ca is not None and ca.tzinfo is None:
        ca = ca.replace(tzinfo=timezone.utc)
    ua = fb.updated_at
    if ua is not None and ua.tzinfo is None:
        ua = ua.replace(tzinfo=timezone.utc)
    return {
        "id": str(fb.id),
        "turn_id": str(fb.turn_id),
        "user_id": str(fb.user_id),
        "rating": fb.rating,
        "comment": fb.comment,
        "updated": updated,
        "created_at": ca.isoformat() if ca else None,
        "updated_at": ua.isoformat() if ua else None,
    }
