"""E2.5 · Flight approval template REST endpoints.

Endpoints
=========
POST   /approval-templates              create
GET    /approval-templates              list (org-scoped)
GET    /approval-templates/{id}         fetch one
PATCH  /approval-templates/{id}         update
DELETE /approval-templates/{id}         soft-delete
POST   /approval-templates/{id}/apply   instantiate a new flight_approval
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.approval_templates import (
    TemplateError,
    apply_to_new_approval,
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)


router = APIRouter(
    prefix="/approval-templates",
    tags=["approval-templates"],
)


# ============================================================ Schemas ==


class TemplateOut(BaseModel):
    id: UUID
    org_id: UUID
    author_user_id: UUID
    name: str
    category: str
    purpose: str | None
    pilot_name: str | None
    pilot_license: str | None
    aircraft_reg: str | None
    aircraft_model: str | None
    insurance_no: str | None
    max_alt_m: float | None
    min_alt_m: float | None
    default_area_polygon: list | None
    authorities_preset: list[dict[str, Any]]
    checklist_json: list[dict[str, Any]]
    apply_count: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

    @classmethod
    def from_row(cls, r) -> "TemplateOut":
        return cls(
            id=r.id,
            org_id=r.org_id,
            author_user_id=r.author_user_id,
            name=r.name,
            category=r.category,
            purpose=r.purpose,
            pilot_name=r.pilot_name,
            pilot_license=r.pilot_license,
            aircraft_reg=r.aircraft_reg,
            aircraft_model=r.aircraft_model,
            insurance_no=r.insurance_no,
            max_alt_m=r.max_alt_m,
            min_alt_m=r.min_alt_m,
            default_area_polygon=r.default_area_polygon,
            authorities_preset=r.authorities_preset or [],
            checklist_json=r.checklist_json or [],
            apply_count=r.apply_count or 0,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )


class CreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    category: str = "routine"
    purpose: str | None = None
    pilot_name: str | None = None
    pilot_license: str | None = None
    aircraft_reg: str | None = None
    aircraft_model: str | None = None
    insurance_no: str | None = None
    max_alt_m: float | None = None
    min_alt_m: float | None = None
    default_area_polygon: list | None = None
    authorities_preset: list[dict[str, Any]] = Field(default_factory=list)
    checklist_json: list[dict[str, Any]] = Field(default_factory=list)


class UpdatePayload(BaseModel):
    name: str | None = None
    category: str | None = None
    purpose: str | None = None
    pilot_name: str | None = None
    pilot_license: str | None = None
    aircraft_reg: str | None = None
    aircraft_model: str | None = None
    insurance_no: str | None = None
    max_alt_m: float | None = None
    min_alt_m: float | None = None
    default_area_polygon: list | None = None
    authorities_preset: list[dict[str, Any]] | None = None
    checklist_json: list[dict[str, Any]] | None = None


class ApplyPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    start_ts: datetime
    end_ts: datetime
    area_polygon_override: list | None = None
    max_alt_m_override: float | None = None
    min_alt_m_override: float | None = None


class ApplyResponse(BaseModel):
    approval_id: UUID
    status: str


# ============================================================= Endpoints


def _map_error(exc: TemplateError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg.lower():
        return HTTPException(404, msg)
    return HTTPException(400, msg)


@router.post("", response_model=TemplateOut, status_code=201)
async def api_create(
    payload: CreatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    try:
        row = await create_template(
            db,
            org_id=user.org_id,
            author_user_id=user.id,
            name=payload.name,
            category=payload.category,
            purpose=payload.purpose,
            pilot_name=payload.pilot_name,
            pilot_license=payload.pilot_license,
            aircraft_reg=payload.aircraft_reg,
            aircraft_model=payload.aircraft_model,
            insurance_no=payload.insurance_no,
            max_alt_m=payload.max_alt_m,
            min_alt_m=payload.min_alt_m,
            default_area_polygon=payload.default_area_polygon,
            authorities_preset=payload.authorities_preset,
            checklist_json=payload.checklist_json,
        )
    except TemplateError as exc:
        raise _map_error(exc)
    return TemplateOut.from_row(row)


@router.get("", response_model=list[TemplateOut])
async def api_list(
    category: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TemplateOut]:
    try:
        rows = await list_templates(
            db, org_id=user.org_id, category=category,
            limit=min(max(limit, 1), 500),
        )
    except TemplateError as exc:
        raise _map_error(exc)
    return [TemplateOut.from_row(r) for r in rows]


@router.get("/{template_id}", response_model=TemplateOut)
async def api_get(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    row = await get_template(db, org_id=user.org_id, template_id=template_id)
    if row is None:
        raise HTTPException(404, "template not found")
    return TemplateOut.from_row(row)


@router.patch("/{template_id}", response_model=TemplateOut)
async def api_update(
    template_id: UUID,
    patch: UpdatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateOut:
    body = {k: v for k, v in patch.dict().items() if v is not None}
    try:
        row = await update_template(
            db, org_id=user.org_id,
            template_id=template_id, patch=body,
        )
    except TemplateError as exc:
        raise _map_error(exc)
    return TemplateOut.from_row(row)


@router.delete("/{template_id}", status_code=204)
async def api_delete(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    ok = await delete_template(
        db, org_id=user.org_id, template_id=template_id,
    )
    if not ok:
        raise HTTPException(404, "template not found")


@router.post(
    "/{template_id}/apply", response_model=ApplyResponse,
)
async def api_apply(
    template_id: UUID,
    payload: ApplyPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApplyResponse:
    try:
        approval = await apply_to_new_approval(
            db,
            org_id=user.org_id,
            template_id=template_id,
            created_by=user.id,
            title=payload.title,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
            area_polygon_override=payload.area_polygon_override,
            max_alt_m_override=payload.max_alt_m_override,
            min_alt_m_override=payload.min_alt_m_override,
        )
    except TemplateError as exc:
        raise _map_error(exc)
    return ApplyResponse(approval_id=approval.id, status=approval.status)
