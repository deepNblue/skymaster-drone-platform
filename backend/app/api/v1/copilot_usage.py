"""F4.3 · Copilot usage & quota REST."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models.user import User
from app.services.copilot_usage import (
    check_quota, daily_rollup, get_org_month_usage, get_org_quota,
    model_rollup, persona_rollup, set_org_quota,
)


router = APIRouter(prefix="/copilot/usage", tags=["copilot-usage"])


class QuotaIn(BaseModel):
    monthly_token_budget: int = Field(..., ge=0, le=1_000_000_000)
    hard_stop: bool = False


@router.get("/me/month")
async def api_my_month(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await get_org_month_usage(db, org_id=user.org_id)


@router.get("/me/daily")
async def api_my_daily(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await daily_rollup(db, org_id=user.org_id, days=days)


@router.get("/me/persona")
async def api_my_persona(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await persona_rollup(db, org_id=user.org_id, days=days)


@router.get("/me/quota")
async def api_my_quota(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await check_quota(db, org_id=user.org_id)


# ---- Admin cross-tenant + policy CRUD ----

@router.get("/models")
async def api_models(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner")),
) -> list[dict[str, Any]]:
    return await model_rollup(db, days=days)


@router.get("/orgs/{org_id}/month")
async def api_org_month(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner")),
) -> dict[str, Any]:
    return await get_org_month_usage(db, org_id=org_id)


@router.put("/orgs/{org_id}/quota", status_code=200)
async def api_set_quota(
    org_id: UUID,
    body: QuotaIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner")),
) -> dict[str, Any]:
    try:
        return await set_org_quota(
            db,
            org_id=org_id,
            monthly_token_budget=body.monthly_token_budget,
            hard_stop=body.hard_stop,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/orgs/{org_id}/quota")
async def api_get_quota(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner")),
) -> dict[str, Any]:
    r = await get_org_quota(db, org_id=org_id)
    if r is None:
        raise HTTPException(404, "no quota set")
    return r


@router.get("/orgs/{org_id}/check")
async def api_check_quota(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner")),
) -> dict[str, Any]:
    return await check_quota(db, org_id=org_id)
