"""REST API for scene moderation reports & appeals — v2.1 T2.2."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services import scene_moderation as mod_svc


router = APIRouter(prefix="/marketplace/scenes", tags=["scene-moderation"])


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) not in ("admin", "superadmin"):
        raise HTTPException(403, "admin-only endpoint")


def _map_err(e: mod_svc.ModerationError) -> HTTPException:
    s = str(e)
    if "not found" in s:
        return HTTPException(404, s)
    return HTTPException(400, s)


# ---------- schemas -------------------------------------------------------


class ReportBody(BaseModel):
    category: str
    details: Optional[str] = Field(None, max_length=4000)


class ReportOut(BaseModel):
    id: UUID
    listing_id: UUID
    reporter_user_id: Optional[UUID]
    category: str
    details: Optional[str]
    status: str
    resolution_note: Optional[str]

    class Config:
        from_attributes = True


class ReportFileResponse(BaseModel):
    report: ReportOut
    auto_hidden: bool


class ReportPage(BaseModel):
    total: int
    items: list[ReportOut]
    limit: int
    offset: int


class ReportSummary(BaseModel):
    total: int
    by_status: dict[str, int]
    by_category: dict[str, int]


class ResolveReportBody(BaseModel):
    new_status: str
    note: Optional[str] = Field(None, max_length=2000)
    take_down_reason: Optional[str] = Field(None, max_length=1000)


class AppealBody(BaseModel):
    appeal_message: str = Field(..., min_length=1, max_length=4000)


class AppealOut(BaseModel):
    id: UUID
    listing_id: UUID
    appeal_seq: int
    appellant_user_id: Optional[UUID]
    original_status: str
    appeal_message: str
    status: str
    resolution_note: Optional[str]

    class Config:
        from_attributes = True


class AppealPage(BaseModel):
    total: int
    items: list[AppealOut]
    limit: int
    offset: int


class ResolveAppealBody(BaseModel):
    accept: bool
    note: Optional[str] = Field(None, max_length=2000)


# ---------- report endpoints ---------------------------------------------


@router.post("/{listing_id}/reports", response_model=ReportFileResponse, status_code=201)
async def file_report(
    listing_id: UUID,
    body: ReportBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportFileResponse:
    try:
        report, auto_hidden = await mod_svc.file_report(db, mod_svc.ReportParams(
            listing_id=listing_id,
            reporter_user_id=user.id,
            reporter_org_id=user.org_id,
            category=body.category,
            details=body.details,
        ))
    except mod_svc.ModerationError as e:
        raise _map_err(e)
    await db.commit()
    return ReportFileResponse(report=report, auto_hidden=auto_hidden)


@router.get("/reports", response_model=ReportPage)
async def list_reports(
    status: Optional[str] = None,
    listing_id: Optional[UUID] = None,
    category: Optional[str] = None,
    limit: int = 50, offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportPage:
    _require_admin(user)
    try:
        rows, total = await mod_svc.list_reports(
            db, status=status, listing_id=listing_id, category=category,
            limit=limit, offset=offset,
        )
    except mod_svc.ModerationError as e:
        raise _map_err(e)
    return ReportPage(total=total, items=list(rows), limit=limit, offset=offset)


@router.get("/{listing_id}/reports/summary", response_model=ReportSummary)
async def report_summary(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportSummary:
    _require_admin(user)
    summary = await mod_svc.report_summary_by_listing(db, listing_id)
    return ReportSummary(**summary)


@router.post("/reports/{report_id}/resolve", response_model=ReportOut)
async def resolve_report(
    report_id: UUID,
    body: ResolveReportBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    _require_admin(user)
    try:
        r = await mod_svc.resolve_report(
            db, report_id=report_id, resolver_user_id=user.id,
            new_status=body.new_status, note=body.note,
            take_down_reason=body.take_down_reason,
        )
    except mod_svc.ModerationError as e:
        raise _map_err(e)
    await db.commit()
    return r


# ---------- appeal endpoints ---------------------------------------------


@router.post("/{listing_id}/appeals", response_model=AppealOut, status_code=201)
async def file_appeal(
    listing_id: UUID,
    body: AppealBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AppealOut:
    try:
        appeal = await mod_svc.file_appeal(db, mod_svc.AppealParams(
            listing_id=listing_id,
            appellant_user_id=user.id,
            appellant_org_id=user.org_id,
            appeal_message=body.appeal_message,
        ))
    except mod_svc.ModerationError as e:
        raise _map_err(e)
    await db.commit()
    return appeal


@router.get("/appeals", response_model=AppealPage)
async def list_appeals(
    status: Optional[str] = None,
    listing_id: Optional[UUID] = None,
    limit: int = 50, offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AppealPage:
    _require_admin(user)
    try:
        rows, total = await mod_svc.list_appeals(
            db, status=status, listing_id=listing_id, limit=limit, offset=offset,
        )
    except mod_svc.ModerationError as e:
        raise _map_err(e)
    return AppealPage(total=total, items=list(rows), limit=limit, offset=offset)


@router.post("/appeals/{appeal_id}/resolve", response_model=AppealOut)
async def resolve_appeal(
    appeal_id: UUID,
    body: ResolveAppealBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AppealOut:
    _require_admin(user)
    try:
        r = await mod_svc.resolve_appeal(
            db, appeal_id=appeal_id, resolver_user_id=user.id,
            accept=body.accept, note=body.note,
        )
    except mod_svc.ModerationError as e:
        raise _map_err(e)
    await db.commit()
    return r


@router.post("/appeals/{appeal_id}/withdraw", response_model=AppealOut)
async def withdraw_appeal(
    appeal_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AppealOut:
    try:
        r = await mod_svc.withdraw_appeal(
            db, appeal_id=appeal_id,
            actor_user_id=user.id, actor_org_id=user.org_id,
        )
    except mod_svc.ModerationError as e:
        raise _map_err(e)
    await db.commit()
    return r
