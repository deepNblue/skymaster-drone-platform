"""API: /copilot/tool-policy — org tool policy CRUD + audit query (v2.1 F4.4)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services import copilot_tool_policy as svc
from app.services.tool_registry import get_registry

router = APIRouter(prefix="/copilot/tool-policy", tags=["copilot-tool-policy"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ToolCatalogItem(BaseModel):
    name: str
    description: str
    permission: str
    risk_level: str


class PolicyOut(BaseModel):
    org_id: UUID
    allowlist: list[str] | None = None
    blocklist: list[str] | None = None
    max_risk_level: str | None = None
    require_approval_above: str | None = None
    updated_at: datetime | None = None


class PolicyIn(BaseModel):
    allowlist: list[str] | None = Field(
        default=None,
        description="If non-empty, only listed tools may run.",
    )
    blocklist: list[str] | None = None
    max_risk_level: str | None = Field(
        default=None,
        description="Cap: low|medium|high|critical.",
    )
    require_approval_above: str | None = Field(
        default=None,
        description="Force approval at/above this risk tier.",
    )


class AuditOut(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID
    session_id: UUID | None = None
    trace_id: UUID | None = None
    tool_name: str
    permission: str
    risk_level: str
    status: str
    arguments: dict[str, Any] | None = None
    result_preview: str | None = None
    error: str | None = None
    latency_ms: int | None = None
    reason: str | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Tool catalog (readonly — list registered tools + their risk tag)
# ---------------------------------------------------------------------------
@router.get("/tools", response_model=list[ToolCatalogItem])
async def api_list_tools(
    user: User = Depends(get_current_user),  # noqa: ARG001
) -> list[ToolCatalogItem]:
    reg = get_registry()
    out: list[ToolCatalogItem] = []
    for name in reg.names():
        spec = reg.get(name)
        if spec is None:
            continue
        out.append(ToolCatalogItem(
            name=spec.name,
            description=spec.description,
            permission=spec.permission,
            risk_level=spec.risk_level,
        ))
    out.sort(key=lambda x: (x.risk_level, x.name))
    return out


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------
@router.get("/me", response_model=PolicyOut | None)
async def api_get_my_policy(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PolicyOut | None:
    policy = await svc.get_policy(db, org_id=user.org_id)
    if not policy:
        return None
    return PolicyOut.model_validate(policy, from_attributes=True)


@router.put("/me", response_model=PolicyOut)
async def api_put_my_policy(
    body: PolicyIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PolicyOut:
    # Validate risk-tier fields
    valid_tiers = {None, "low", "medium", "high", "critical"}
    if body.max_risk_level not in valid_tiers:
        raise HTTPException(400, "invalid max_risk_level")
    if body.require_approval_above not in valid_tiers:
        raise HTTPException(400, "invalid require_approval_above")

    # Validate tool names against registry
    reg = get_registry()
    known = set(reg.names())
    for lst_name, lst in [
        ("allowlist", body.allowlist),
        ("blocklist", body.blocklist),
    ]:
        for t in (lst or []):
            if t not in known:
                raise HTTPException(400, f"unknown tool in {lst_name}: {t}")

    policy = await svc.upsert_policy(
        db,
        org_id=user.org_id,
        allowlist=body.allowlist,
        blocklist=body.blocklist,
        max_risk_level=body.max_risk_level,
        require_approval_above=body.require_approval_above,
    )
    return PolicyOut.model_validate(policy, from_attributes=True)


# ---------------------------------------------------------------------------
# Audit query
# ---------------------------------------------------------------------------
@router.get("/audits", response_model=list[AuditOut])
async def api_list_audits(
    tool_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AuditOut]:
    rows = await svc.list_audits(
        db,
        org_id=user.org_id,
        tool_name=tool_name,
        status=status,
        risk_level=risk_level,
        limit=limit,
        offset=offset,
    )
    return [AuditOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/audits/stats", response_model=dict[str, dict[str, int]])
async def api_audit_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, dict[str, int]]:
    return await svc.audit_stats(db, org_id=user.org_id)
