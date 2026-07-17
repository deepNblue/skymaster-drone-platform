"""E3.3 · Detection alert rules REST + evaluation trigger."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.detection_alert import (
    AlertRuleError, create_rule, delete_rule, evaluate_rules, get_rule,
    list_rules, update_rule,
)
from app.services.detection_cluster import cluster_analytics


router = APIRouter(prefix="/vision/alerts", tags=["vision-alerts"])


def _map(exc: AlertRuleError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


class RuleCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=64)
    min_member_count: int = Field(3, ge=1)
    min_peak_confidence: float = Field(0.0, ge=0.0, le=1.0)
    action: str = "log"
    cooldown_seconds: int = Field(300, ge=0)
    notes: str | None = None


class RuleUpdateIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    label: str | None = Field(None, min_length=1, max_length=64)
    min_member_count: int | None = Field(None, ge=1)
    min_peak_confidence: float | None = Field(None, ge=0.0, le=1.0)
    action: str | None = None
    cooldown_seconds: int | None = Field(None, ge=0)
    enabled: bool | None = None
    notes: str | None = None


def _serialize(r) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "name": r.name,
        "label": r.label,
        "min_member_count": r.min_member_count,
        "min_peak_confidence": r.min_peak_confidence,
        "action": r.action,
        "cooldown_seconds": r.cooldown_seconds,
        "enabled": r.enabled,
        "last_fired_at":
            r.last_fired_at.isoformat() if r.last_fired_at else None,
        "notes": r.notes,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


@router.get("")
async def api_list(
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    rows = await list_rules(
        db, org_id=user.org_id, enabled_only=enabled_only,
    )
    return [_serialize(r) for r in rows]


@router.post("", status_code=201)
async def api_create(
    payload: RuleCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        r = await create_rule(
            db, org_id=user.org_id, **payload.model_dump(),
        )
    except AlertRuleError as e:
        raise _map(e)
    return _serialize(r)


@router.get("/{rule_id}")
async def api_get(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        r = await get_rule(db, org_id=user.org_id, rule_id=rule_id)
    except AlertRuleError as e:
        raise _map(e)
    return _serialize(r)


@router.patch("/{rule_id}")
async def api_update(
    rule_id: UUID,
    payload: RuleUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        r = await update_rule(
            db, org_id=user.org_id, rule_id=rule_id,
            **payload.model_dump(exclude_none=True),
        )
    except AlertRuleError as e:
        raise _map(e)
    return _serialize(r)


@router.delete("/{rule_id}", status_code=204)
async def api_delete(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        await delete_rule(db, org_id=user.org_id, rule_id=rule_id)
    except AlertRuleError as e:
        raise _map(e)


@router.post("/evaluate")
async def api_evaluate(
    since_seconds: int = 3600,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Run current cluster analytics and evaluate all enabled rules.

    Suitable for manual "test fire" from the UI or for a cron job.
    """
    analytics = await cluster_analytics(
        db, tenant_id=user.org_id, since_seconds=since_seconds,
    )
    fires = await evaluate_rules(
        db, org_id=user.org_id,
        clusters=analytics["clusters"],
    )
    return {
        "evaluated_at": analytics["window_seconds"],
        "total_clusters": analytics["cluster_count"],
        "fires": fires,
        "fire_count": len(fires),
    }
