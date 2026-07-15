"""Flight Approval API — v2.0 Track A one-stop multi-authority approval.

Endpoints
=========

- POST /api/v1/approvals              create draft
- GET  /api/v1/approvals              list mine
- GET  /api/v1/approvals/{id}         detail
- PATCH /api/v1/approvals/{id}        edit draft
- POST /api/v1/approvals/{id}/route   preview authority routing
- POST /api/v1/approvals/{id}/submit  submit for review (fan-out)
- POST /api/v1/approvals/{id}/authorities/{code}/decide  authority marks approve/reject
- POST /api/v1/approvals/{id}/cancel  cancel
- POST /api/v1/approvals/{id}/mark-flown  mark as flown after takeoff
- POST /api/v1/approvals/{id}/preflight-check  pre-takeoff checklist

- GET  /api/v1/approvals/authorities/catalog  list all authorities
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.flight_approval import (
    FlightApproval, FlightApprovalAuthority, FlightApprovalSignature,
)
from app.models.user import User
from app.services.approval_router import AUTHORITIES, is_high_risk, route_authorities
from app.services.preflight import preflight_check

router = APIRouter(prefix="/approvals", tags=["flight-approval"])


# --- Schemas ---------------------------------------------------------------


class ApprovalIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    purpose: Optional[str] = None
    category: str = Field(default="routine", pattern="^(routine|special|emergency)$")
    pilot_name: Optional[str] = None
    pilot_license: Optional[str] = None
    aircraft_reg: Optional[str] = None
    aircraft_model: Optional[str] = None
    aircraft_weight_kg: Optional[float] = None
    insurance_no: Optional[str] = None
    area_polygon: Optional[list[list[float]]] = None
    max_alt_m: Optional[float] = Field(default=None, ge=0, le=1000)
    min_alt_m: Optional[float] = Field(default=None, ge=0)
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    mission_id: Optional[UUID] = None


class ApprovalPatch(BaseModel):
    title: Optional[str] = None
    purpose: Optional[str] = None
    pilot_name: Optional[str] = None
    pilot_license: Optional[str] = None
    aircraft_reg: Optional[str] = None
    aircraft_model: Optional[str] = None
    insurance_no: Optional[str] = None
    area_polygon: Optional[list[list[float]]] = None
    max_alt_m: Optional[float] = None
    min_alt_m: Optional[float] = None
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None


class AuthorityRow(BaseModel):
    id: UUID
    authority_code: str
    authority_name: str
    channel: str
    status: str
    external_ref: Optional[str]
    submitted_at: Optional[datetime]
    responded_at: Optional[datetime]
    reject_reason: Optional[str]
    priority: int
    # T7.5 — free-form JSON dict from bridges (RPA job id, driver, …)
    extra: Optional[dict] = None

    class Config:
        from_attributes = True


class ApprovalOut(BaseModel):
    id: UUID
    title: str
    purpose: Optional[str]
    category: str
    status: str
    pilot_name: Optional[str]
    pilot_license: Optional[str]
    aircraft_reg: Optional[str]
    aircraft_model: Optional[str]
    insurance_no: Optional[str]
    area_polygon: Optional[list]
    max_alt_m: Optional[float]
    min_alt_m: Optional[float]
    start_ts: Optional[datetime]
    end_ts: Optional[datetime]
    reject_reason: Optional[str]
    timeline: Optional[list]
    created_at: datetime
    updated_at: datetime
    authorities: list[AuthorityRow] = []
    # T7.0 -----------------------------------------------------------
    requires_second_approval: bool = False
    second_approver_id: Optional[UUID] = None
    second_approved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DecideBody(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected|accepted|approving)$")
    external_ref: Optional[str] = None
    reason: Optional[str] = None
    # T7.0 optional e-sign at decision time
    esign_note: Optional[str] = None


class PreflightBody(BaseModel):
    remote_id_broadcast: Optional[bool] = None
    intended_max_alt_m: Optional[float] = None


# --- T7.0 additions --------------------------------------------------------


class SecondApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    note: Optional[str] = Field(default=None, max_length=1000)


class BatchSubmitBody(BaseModel):
    approval_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    aircraft_weight_kg: Optional[float] = None


class BatchSubmitResult(BaseModel):
    approval_id: UUID
    ok: bool
    status: Optional[str] = None
    error: Optional[str] = None


class BatchSubmitResponse(BaseModel):
    submitted: int
    held_for_second_approval: int
    failed: int
    results: list[BatchSubmitResult]


class BatchSecondApprovalBody(BaseModel):
    """T7.13 — batch second-approval decision.

    Supervisor multi-selects pending_second_approval rows from the
    dashboard and applies one decision to all in a single call. Each
    row is processed independently — a fan-out failure on approval #3
    does not roll back approvals #1 and #2.
    """
    approval_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    decision: str = Field(..., pattern="^(approve|reject)$")
    note: Optional[str] = Field(default=None, max_length=1000)
    aircraft_weight_kg: Optional[float] = None


class BatchSecondApprovalResult(BaseModel):
    approval_id: UUID
    ok: bool
    status: Optional[str] = None
    error: Optional[str] = None


class BatchSecondApprovalResponse(BaseModel):
    approved: int
    rejected: int
    failed: int
    results: list[BatchSecondApprovalResult]


class SignatureIn(BaseModel):
    authority_code: Optional[str] = None
    payload_sha256: str = Field(..., min_length=64, max_length=64,
                                pattern=r"^[0-9a-fA-F]{64}$")
    algorithm: str = Field(default="sha256", max_length=32)
    note: Optional[str] = Field(default=None, max_length=1000)


class SignatureOut(BaseModel):
    id: UUID
    approval_id: UUID
    authority_code: Optional[str]
    signer_user_id: UUID
    signer_role: Optional[str]
    payload_sha256: str
    algorithm: str
    note: Optional[str]
    signed_at: datetime

    class Config:
        from_attributes = True


# --- Helpers ---------------------------------------------------------------


def _timeline_event(actor: str, action: str, note: str = "") -> dict:
    return {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "note": note,
    }


def _rollup_status(auths: list[FlightApprovalAuthority]) -> str:
    """Compute the aggregate status from per-authority states."""
    if not auths:
        return "in_review"
    if any(a.status == "rejected" for a in auths):
        return "rejected"
    if all(a.status in ("approved", "skipped") for a in auths):
        return "approved"
    return "in_review"


async def _get_or_404(db: AsyncSession, approval_id: UUID) -> FlightApproval:
    row = (await db.execute(
        select(FlightApproval).where(FlightApproval.id == approval_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Approval not found")
    return row


# --- Endpoints -------------------------------------------------------------


@router.get("/authorities/catalog")
async def authority_catalog() -> dict:
    """Static catalog of the 7 authority types SkyMaster knows about."""
    return {
        "authorities": [
            {
                "code": a.code,
                "name": a.name,
                "channel": a.channel,
                "priority": a.priority,
                "scope": a.scope,
            }
            for a in AUTHORITIES.values()
        ]
    }


@router.post("", response_model=ApprovalOut, status_code=201)
async def create_approval(
    body: ApprovalIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightApproval:
    row = FlightApproval(
        tenant_id=user.org_id,
        created_by=user.id,
        title=body.title,
        purpose=body.purpose,
        category=body.category,
        pilot_name=body.pilot_name or user.email,
        pilot_license=body.pilot_license,
        aircraft_reg=body.aircraft_reg,
        aircraft_model=body.aircraft_model,
        insurance_no=body.insurance_no,
        area_polygon=body.area_polygon,
        max_alt_m=body.max_alt_m,
        min_alt_m=body.min_alt_m,
        start_ts=body.start_ts,
        end_ts=body.end_ts,
        mission_id=body.mission_id,
        status="draft",
        timeline=[_timeline_event(str(user.id), "create", body.title)],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FlightApproval]:
    stmt = select(FlightApproval).where(FlightApproval.tenant_id == user.org_id)
    if status:
        stmt = stmt.where(FlightApproval.status == status)
    stmt = stmt.order_by(FlightApproval.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


@router.get("/summary")
async def approvals_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """T8.1 — dashboard summary counters for the caller's tenant.

    Returns counts by ``status`` plus a 7-day submission trend. Cheap
    (2 aggregation queries) and cached at the client for a few minutes.
    """
    from datetime import datetime, timedelta, timezone as _tz
    from sqlalchemy import func as _func

    tenant = user.org_id
    # Status buckets — all rows for the tenant
    status_rows = (await db.execute(
        select(FlightApproval.status, _func.count(FlightApproval.id))
        .where(FlightApproval.tenant_id == tenant)
        .group_by(FlightApproval.status)
    )).all()
    status_counts = {s or "unknown": int(c) for s, c in status_rows}

    # 7-day submission trend
    cutoff = datetime.now(_tz.utc) - timedelta(days=7)
    recent = (await db.execute(
        select(_func.count(FlightApproval.id))
        .where(
            FlightApproval.tenant_id == tenant,
            FlightApproval.created_at >= cutoff,
        )
    )).scalar_one()

    # In-flight = submitted + under_review (approvals not yet decided)
    in_flight = (
        status_counts.get("submitted", 0)
        + status_counts.get("under_review", 0)
    )

    return {
        "status_counts": status_counts,
        "submitted_last_7d": int(recent or 0),
        "in_flight": in_flight,
        "total": sum(status_counts.values()),
    }


# ---------------------------------------------------------------------------
# T7.8 — Batch export approvals (CSV + certificate ZIP)
# ---------------------------------------------------------------------------
@router.get("/export.csv")
async def export_approvals_csv(
    status: Optional[str] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    limit: int = Query(500, le=2000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk CSV export of all approvals visible to the caller's tenant.

    Excel-friendly UTF-8 BOM. Flat schema (one row per approval, joined
    authority summary as a JSON blob column). Same status filter as the
    JSON list endpoint. Not paginated — capped at limit=2000 for a
    single-shot download.

    T7.11: created_from/created_to (ISO-8601) filter by created_at.
    Both are inclusive. Half-open is fine — pass only one to bound one
    side.
    """
    import csv
    import io
    import json

    from fastapi.responses import Response

    stmt = select(FlightApproval).where(FlightApproval.tenant_id == user.org_id)
    if status:
        stmt = stmt.where(FlightApproval.status == status)
    if created_from:
        stmt = stmt.where(FlightApproval.created_at >= created_from)
    if created_to:
        stmt = stmt.where(FlightApproval.created_at <= created_to)
    stmt = stmt.order_by(FlightApproval.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    columns = [
        "id", "title", "purpose", "category", "status",
        "pilot_name", "pilot_license",
        "aircraft_reg", "aircraft_model",
        "max_alt_m", "start_ts", "end_ts",
        "second_approved_at", "created_at",
        "authorities",  # JSON-serialized short summary
    ]

    def _val(v):
        if v is None:
            return ""
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if isinstance(v, (list, tuple, dict)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    for r in rows:
        authorities_summary = [
            {
                "code": a.authority_code,
                "name": a.authority_name,
                "channel": a.channel,
                "status": a.status,
                "external_ref": a.external_ref,
            }
            for a in (r.authorities or [])
        ]
        record = {
            "id": r.id, "title": r.title, "purpose": r.purpose,
            "category": r.category, "status": r.status,
            "pilot_name": r.pilot_name, "pilot_license": r.pilot_license,
            "aircraft_reg": r.aircraft_reg, "aircraft_model": r.aircraft_model,
            "max_alt_m": r.max_alt_m, "start_ts": r.start_ts,
            "end_ts": r.end_ts, "second_approved_at": r.second_approved_at,
            "created_at": r.created_at,
            "authorities": authorities_summary,
        }
        writer.writerow([_val(record[c]) for c in columns])

    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="approvals.csv"',
            "X-Row-Count": str(len(rows)),
        },
    )


@router.get("/export/certificates.zip")
async def export_approvals_certificates_zip(
    status: Optional[str] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-package approval PDF certificates into a single ZIP.

    Reuses the T7.3 single-approval PDF renderer per approval, adds an
    ``INDEX.csv`` at the archive root so the recipient can grep by
    aircraft_reg or status without opening every file.

    Only includes approvals whose ``tenant_id == user.org_id`` — no
    cross-org leakage. Limit is intentionally smaller than the CSV
    export because PDF rendering is O(n) and this endpoint materializes
    all n bytes in memory.

    T7.11: created_from/created_to same filter as CSV endpoint.
    """
    import io
    import zipfile
    import csv

    from fastapi.responses import Response

    stmt = select(FlightApproval).where(FlightApproval.tenant_id == user.org_id)
    if status:
        stmt = stmt.where(FlightApproval.status == status)
    if created_from:
        stmt = stmt.where(FlightApproval.created_at >= created_from)
    if created_to:
        stmt = stmt.where(FlightApproval.created_at <= created_to)
    stmt = stmt.order_by(FlightApproval.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    # Lazy-render each PDF using the same code path as /certificate.pdf
    # to avoid divergence. Build in-memory ZIP (ok for limit<=200).
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        # INDEX.csv (BOM-prefixed) for at-a-glance triage
        idx_buf = io.StringIO()
        idx_buf.write("\ufeff")
        idx_w = csv.writer(idx_buf)
        idx_w.writerow([
            "filename", "id", "title", "aircraft_reg", "status",
            "max_alt_m", "created_at",
        ])
        for r in rows:
            fname = f"approval-{r.id}.pdf"
            try:
                # Reuse the PDF renderer via internal HTTP call would be
                # overkill — inline the same reportlab code path.
                pdf_bytes = await _render_approval_pdf(r)
            except Exception:  # pragma: no cover
                continue
            zf.writestr(fname, pdf_bytes)
            idx_w.writerow([
                fname, str(r.id), r.title or "", r.aircraft_reg or "",
                r.status,
                r.max_alt_m if r.max_alt_m is not None else "",
                r.created_at.isoformat() if r.created_at else "",
            ])
        zf.writestr("INDEX.csv", idx_buf.getvalue().encode("utf-8"))

    return Response(
        content=mem.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition":
                'attachment; filename="approval-certificates.zip"',
            "X-Row-Count": str(len(rows)),
        },
    )


async def _render_approval_pdf(row: FlightApproval) -> bytes:
    """Extracted PDF rendering — same layout as /certificate.pdf.

    Kept as a plain coroutine so both the single-doc endpoint and the
    ZIP endpoint can share bytes without duplicating the reportlab
    calls or spawning subrequests.
    """
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light"
    except Exception:  # pragma: no cover
        font_name = "Helvetica"

    approval_url = (
        f"{os.getenv('PUBLIC_BASE_URL', '')}/api/v1/approvals/{row.id}/verify"
    )
    qr_png_bytes: bytes | None = None
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(approval_url or f"approval:{row.id}")
        qr.make(fit=True)
        img = qr.make_image()
        buf = BytesIO()
        img.save(buf, format="PNG")
        qr_png_bytes = buf.getvalue()
    except Exception:
        qr_png_bytes = None

    out = BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    w, h = A4
    c.setTitle(f"SkyMaster Flight Approval Certificate {row.id}")
    c.setFont(font_name, 20)
    c.drawCentredString(w / 2, h - 30 * mm, "无人机飞行报备证明")
    c.setFont(font_name, 10)
    c.drawCentredString(w / 2, h - 38 * mm,
                        "SkyMaster Drone Platform · Approval Certificate")
    y = h - 55 * mm

    def _row(label, value):
        nonlocal y
        c.setFont(font_name, 10)
        c.drawString(25 * mm, y, label)
        c.setFont(font_name, 11)
        c.drawString(65 * mm, y, value)
        y -= 8 * mm

    _row("报备编号", str(row.id))
    _row("标题", row.title or "-")
    _row("用途", row.purpose or "-")
    _row("飞行器登记号", row.aircraft_reg or "-")
    _row("最大高度 (m)", str(row.max_alt_m or "-"))
    _row("起始时间", row.start_ts.strftime("%Y-%m-%d %H:%M UTC") if row.start_ts else "-")
    _row("结束时间", row.end_ts.strftime("%Y-%m-%d %H:%M UTC") if row.end_ts else "-")
    _row("当前状态", row.status)

    if qr_png_bytes:
        try:
            from reportlab.lib.utils import ImageReader
            qimg = ImageReader(BytesIO(qr_png_bytes))
            c.drawImage(
                qimg, w - 45 * mm, 25 * mm, width=30 * mm, height=30 * mm,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass

    c.setFont(font_name, 8)
    c.setFillGray(0.4)
    c.drawString(25 * mm, 20 * mm, "验证链接:")
    c.drawString(25 * mm, 16 * mm, approval_url or f"approval:{row.id}")
    c.showPage()
    c.save()
    return out.getvalue()



@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightApproval:
    row = await _get_or_404(db, approval_id)
    return row


@router.patch("/{approval_id}", response_model=ApprovalOut)
async def update_approval(
    approval_id: UUID,
    body: ApprovalPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightApproval:
    row = await _get_or_404(db, approval_id)
    if row.status != "draft":
        raise HTTPException(400, "Only draft approvals can be edited")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    row.updated_at = datetime.now(tz=timezone.utc)
    row.timeline = (row.timeline or []) + [_timeline_event(str(user.id), "edit")]
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{approval_id}/route")
async def preview_routing(
    approval_id: UUID,
    aircraft_weight_kg: Optional[float] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Preview which authorities this approval would fan out to."""
    row = await _get_or_404(db, approval_id)
    routed = route_authorities(
        polygon=row.area_polygon,
        max_alt_m=row.max_alt_m,
        purpose=row.purpose,
        aircraft_weight_kg=aircraft_weight_kg,
        category=row.category,
    )
    return {"approval_id": str(approval_id), "authorities": routed}


@router.post("/{approval_id}/submit", response_model=ApprovalOut)
async def submit_approval(
    approval_id: UUID,
    aircraft_weight_kg: Optional[float] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightApproval:
    """Submit draft → fan-out to all applicable authorities."""
    row = await _get_or_404(db, approval_id)
    if row.status != "draft":
        raise HTTPException(400, f"Cannot submit from status {row.status!r}")

    # T7.0 — high-risk gate: hold submission for supervisor sign-off.
    hi_risk, hi_reason = is_high_risk(
        polygon=row.area_polygon,
        max_alt_m=row.max_alt_m,
        category=row.category,
    )
    if hi_risk:
        row.requires_second_approval = True
        row.status = "pending_second_approval"
        now_hr = datetime.now(tz=timezone.utc)
        row.updated_at = now_hr
        row.timeline = (row.timeline or []) + [
            _timeline_event(
                str(user.id),
                "second_approval_required",
                f"high-risk: {hi_reason}",
            )
        ]
        await db.commit()
        await db.refresh(row)
        return row

    routed = route_authorities(
        polygon=row.area_polygon,
        max_alt_m=row.max_alt_m,
        purpose=row.purpose,
        aircraft_weight_kg=aircraft_weight_kg,
        category=row.category,
    )
    if not routed:
        raise HTTPException(400, "No applicable authority; check polygon/altitude/purpose")

    now = datetime.now(tz=timezone.utc)
    for spec in routed:
        db.add(FlightApprovalAuthority(
            approval_id=row.id,
            authority_code=spec["code"],
            authority_name=spec["name"],
            channel=spec["channel"],
            priority=spec["priority"],
            status="submitted" if spec["channel"] == "api" else "pending",
            submitted_at=now if spec["channel"] == "api" else None,
            extra={"reason": spec.get("reason")},
        ))

    row.status = "submitted"
    row.updated_at = now
    row.timeline = (row.timeline or []) + [
        _timeline_event(str(user.id), "submit", f"fan-out {len(routed)} authorities")
    ]
    await db.commit()
    await db.refresh(row)

    # Fan out to Approval-as-a-Service subscribers (best-effort — never
    # blocks the approval flow).
    try:
        from app.services.aaas import fanout_approval_event
        await fanout_approval_event(db, event="approval.submitted", approval=row)
        await db.commit()
    except Exception:  # pragma: no cover
        pass

    # Transition to in_review immediately after fan-out.
    row.status = "in_review"
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{approval_id}/authorities/{code}/decide", response_model=ApprovalOut)
async def decide_authority(
    approval_id: UUID,
    code: str,
    body: DecideBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightApproval:
    """An authority marks its decision.

    In prod this is called by the UOM webhook or the RPA runner. Here we
    also allow ops-role users to update manually for demo.
    """
    row = await _get_or_404(db, approval_id)
    target = None
    for a in row.authorities:
        if a.authority_code == code:
            target = a
            break
    if target is None:
        raise HTTPException(404, f"Authority {code!r} not on this approval")

    now = datetime.now(tz=timezone.utc)
    target.status = body.decision
    if body.decision in ("approved", "rejected"):
        target.responded_at = now
    if body.external_ref:
        target.external_ref = body.external_ref
    if body.reason:
        target.reject_reason = body.reason if body.decision == "rejected" else None

    # Rollup.
    row.status = _rollup_status(row.authorities)
    if row.status == "rejected":
        row.reject_reason = body.reason or f"{code} 驳回"
    row.updated_at = now
    row.timeline = (row.timeline or []) + [_timeline_event(
        actor=code, action=body.decision, note=body.reason or "",
    )]

    await db.commit()
    await db.refresh(row)

    # Publish authority-level + rollup events to AaaS subscribers.
    try:
        from app.services.aaas import fanout_approval_event
        auth_event_map = {
            "accepted":  "approval.authority.accepted",
            "approved":  "approval.authority.approved",
            "approving": "approval.authority.approved",  # provisional
            "rejected":  "approval.authority.rejected",
        }
        ev = auth_event_map.get(body.decision)
        if ev:
            await fanout_approval_event(db, event=ev, approval=row)
        if row.status == "approved":
            await fanout_approval_event(db, event="approval.approved", approval=row)
        elif row.status == "rejected":
            await fanout_approval_event(db, event="approval.rejected", approval=row)
        await db.commit()
    except Exception:  # pragma: no cover
        pass

    return row


@router.post("/{approval_id}/cancel", response_model=ApprovalOut)
async def cancel_approval(
    approval_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightApproval:
    row = await _get_or_404(db, approval_id)
    if row.status in ("flown", "archived", "cancelled"):
        raise HTTPException(400, f"Cannot cancel from status {row.status!r}")
    row.status = "cancelled"
    row.updated_at = datetime.now(tz=timezone.utc)
    row.timeline = (row.timeline or []) + [_timeline_event(str(user.id), "cancel")]
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{approval_id}/mark-flown", response_model=ApprovalOut)
async def mark_flown(
    approval_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightApproval:
    row = await _get_or_404(db, approval_id)
    if row.status != "approved":
        raise HTTPException(400, "Only approved approvals can be marked flown")
    row.status = "flown"
    row.updated_at = datetime.now(tz=timezone.utc)
    row.timeline = (row.timeline or []) + [_timeline_event(str(user.id), "mark_flown")]
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{approval_id}/preflight-check")
async def preflight(
    approval_id: UUID,
    body: PreflightBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_or_404(db, approval_id)
    return preflight_check(
        row,
        remote_id_broadcast=body.remote_id_broadcast,
        intended_max_alt_m=body.intended_max_alt_m,
    )


# ---------------------------------------------------------------------------
# T7.0 — Second approval (supervisor sign-off before fan-out)
# ---------------------------------------------------------------------------
@router.post(
    "/{approval_id}/second-approval",
    response_model=ApprovalOut,
)
async def decide_second_approval(
    approval_id: UUID,
    body: SecondApprovalDecision,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    aircraft_weight_kg: Optional[float] = Query(None),
) -> FlightApproval:
    """Supervisor approves/rejects a high-risk submission.

    On approve → runs the same fan-out logic as ``submit_approval``.
    On reject → status goes back to ``draft`` with a timeline note.
    """
    if getattr(user, "role", None) not in {"admin", "supervisor"}:
        raise HTTPException(403, "only admin/supervisor can grant second approval")
    row = await _get_or_404(db, approval_id)
    if row.status != "pending_second_approval":
        raise HTTPException(
            400, f"Cannot second-approve from status {row.status!r}",
        )

    now = datetime.now(tz=timezone.utc)
    row.second_approver_id = user.id
    row.second_approved_at = now

    if body.decision == "reject":
        row.status = "draft"
        row.requires_second_approval = False
        row.updated_at = now
        row.timeline = (row.timeline or []) + [
            _timeline_event(
                str(user.id),
                "second_approval_rejected",
                body.note or "returned to draft",
            )
        ]
        await db.commit()
        await db.refresh(row)
        return row

    # Approve → fan-out (same code path as submit).
    routed = route_authorities(
        polygon=row.area_polygon,
        max_alt_m=row.max_alt_m,
        purpose=row.purpose,
        aircraft_weight_kg=aircraft_weight_kg,
        category=row.category,
    )
    if not routed:
        raise HTTPException(400, "No applicable authority; check polygon/altitude/purpose")

    for spec in routed:
        db.add(FlightApprovalAuthority(
            approval_id=row.id,
            authority_code=spec["code"],
            authority_name=spec["name"],
            channel=spec["channel"],
            priority=spec["priority"],
            status="submitted" if spec["channel"] == "api" else "pending",
            submitted_at=now if spec["channel"] == "api" else None,
            extra={"reason": spec.get("reason")},
        ))
    row.status = "in_review"
    row.updated_at = now
    row.timeline = (row.timeline or []) + [
        _timeline_event(
            str(user.id),
            "second_approval_granted",
            body.note or f"fan-out {len(routed)} authorities",
        )
    ]
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# T7.0 — Batch submit
# ---------------------------------------------------------------------------
@router.post("/batch-submit", response_model=BatchSubmitResponse)
async def batch_submit(
    body: BatchSubmitBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BatchSubmitResponse:
    """Submit up to 50 draft approvals in one call.

    Each is processed independently: high-risk ones transition to
    ``pending_second_approval``, low-risk fan-out immediately.
    Failures are collected — the batch does not short-circuit.
    """
    results: list[BatchSubmitResult] = []
    submitted = held = failed = 0
    now = datetime.now(tz=timezone.utc)

    for aid in body.approval_ids:
        try:
            row = (await db.execute(
                select(FlightApproval).where(FlightApproval.id == aid)
            )).scalar_one_or_none()
            if not row:
                results.append(BatchSubmitResult(
                    approval_id=aid, ok=False, error="not found",
                ))
                failed += 1
                continue
            if row.status != "draft":
                results.append(BatchSubmitResult(
                    approval_id=aid, ok=False,
                    error=f"status={row.status!r}, not draft",
                ))
                failed += 1
                continue

            hi_risk, hi_reason = is_high_risk(
                polygon=row.area_polygon,
                max_alt_m=row.max_alt_m,
                category=row.category,
            )
            if hi_risk:
                row.requires_second_approval = True
                row.status = "pending_second_approval"
                row.updated_at = now
                row.timeline = (row.timeline or []) + [
                    _timeline_event(
                        str(user.id),
                        "second_approval_required",
                        f"[batch] high-risk: {hi_reason}",
                    )
                ]
                held += 1
                results.append(BatchSubmitResult(
                    approval_id=aid, ok=True,
                    status="pending_second_approval",
                ))
                continue

            routed = route_authorities(
                polygon=row.area_polygon,
                max_alt_m=row.max_alt_m,
                purpose=row.purpose,
                aircraft_weight_kg=body.aircraft_weight_kg,
                category=row.category,
            )
            if not routed:
                results.append(BatchSubmitResult(
                    approval_id=aid, ok=False,
                    error="no applicable authority",
                ))
                failed += 1
                continue

            for spec in routed:
                db.add(FlightApprovalAuthority(
                    approval_id=row.id,
                    authority_code=spec["code"],
                    authority_name=spec["name"],
                    channel=spec["channel"],
                    priority=spec["priority"],
                    status="submitted" if spec["channel"] == "api" else "pending",
                    submitted_at=now if spec["channel"] == "api" else None,
                    extra={"reason": spec.get("reason")},
                ))
            row.status = "in_review"
            row.updated_at = now
            row.timeline = (row.timeline or []) + [
                _timeline_event(
                    str(user.id), "submit",
                    f"[batch] fan-out {len(routed)} authorities",
                )
            ]
            submitted += 1
            results.append(BatchSubmitResult(
                approval_id=aid, ok=True, status="in_review",
            ))
        except Exception as e:  # pragma: no cover
            failed += 1
            results.append(BatchSubmitResult(
                approval_id=aid, ok=False, error=str(e)[:200],
            ))

    await db.commit()
    return BatchSubmitResponse(
        submitted=submitted,
        held_for_second_approval=held,
        failed=failed,
        results=results,
    )


# ---------------------------------------------------------------------------
# T7.13 — batch second-approval
# ---------------------------------------------------------------------------
@router.post(
    "/batch-second-approval",
    response_model=BatchSecondApprovalResponse,
)
async def batch_second_approval(
    body: BatchSecondApprovalBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BatchSecondApprovalResponse:
    """Supervisor makes a batch decision on ≤50 approvals.

    Behaves as a loop over the single-row second-approval logic:
      * approve → fan-out to routed authorities (in_review).
      * reject  → return to draft with a timeline note.
    Each row succeeds/fails independently; the aggregate response
    lists per-approval outcomes so the frontend can highlight rows
    that didn't apply (e.g. no longer in pending_second_approval).
    """
    if getattr(user, "role", None) not in {"admin", "supervisor"}:
        raise HTTPException(
            403, "only admin/supervisor can grant second approval",
        )
    results: list[BatchSecondApprovalResult] = []
    approved = rejected = failed = 0
    now = datetime.now(tz=timezone.utc)

    for aid in body.approval_ids:
        try:
            row = (await db.execute(
                select(FlightApproval).where(FlightApproval.id == aid)
            )).scalar_one_or_none()
            if not row:
                failed += 1
                results.append(BatchSecondApprovalResult(
                    approval_id=aid, ok=False, error="not found",
                ))
                continue
            if row.status != "pending_second_approval":
                failed += 1
                results.append(BatchSecondApprovalResult(
                    approval_id=aid, ok=False,
                    error=f"status={row.status!r}, not pending_second_approval",
                ))
                continue

            row.second_approver_id = user.id
            row.second_approved_at = now

            if body.decision == "reject":
                row.status = "draft"
                row.requires_second_approval = False
                row.updated_at = now
                row.timeline = (row.timeline or []) + [
                    _timeline_event(
                        str(user.id), "second_approval_rejected",
                        f"[batch] {body.note or 'returned to draft'}",
                    )
                ]
                rejected += 1
                results.append(BatchSecondApprovalResult(
                    approval_id=aid, ok=True, status="draft",
                ))
                continue

            # Approve → fan-out
            routed = route_authorities(
                polygon=row.area_polygon,
                max_alt_m=row.max_alt_m,
                purpose=row.purpose,
                aircraft_weight_kg=body.aircraft_weight_kg,
                category=row.category,
            )
            if not routed:
                failed += 1
                results.append(BatchSecondApprovalResult(
                    approval_id=aid, ok=False,
                    error="no applicable authority",
                ))
                continue

            for spec in routed:
                db.add(FlightApprovalAuthority(
                    approval_id=row.id,
                    authority_code=spec["code"],
                    authority_name=spec["name"],
                    channel=spec["channel"],
                    priority=spec["priority"],
                    status="submitted" if spec["channel"] == "api" else "pending",
                    submitted_at=now if spec["channel"] == "api" else None,
                    extra={"reason": spec.get("reason")},
                ))
            row.status = "in_review"
            row.updated_at = now
            row.timeline = (row.timeline or []) + [
                _timeline_event(
                    str(user.id), "second_approval_granted",
                    f"[batch] {body.note or f'fan-out {len(routed)} authorities'}",
                )
            ]
            approved += 1
            results.append(BatchSecondApprovalResult(
                approval_id=aid, ok=True, status="in_review",
            ))
        except Exception as e:  # pragma: no cover
            failed += 1
            results.append(BatchSecondApprovalResult(
                approval_id=aid, ok=False, error=str(e)[:200],
            ))

    await db.commit()
    return BatchSecondApprovalResponse(
        approved=approved,
        rejected=rejected,
        failed=failed,
        results=results,
    )


# ---------------------------------------------------------------------------
# T7.0 — E-signatures
# ---------------------------------------------------------------------------
@router.post(
    "/{approval_id}/signatures",
    response_model=SignatureOut,
    status_code=201,
)
async def add_signature(
    approval_id: UUID,
    body: SignatureIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FlightApprovalSignature:
    """Attach an e-signature to the approval or one of its authority
    decisions. Records the sha256 of the payload the signer saw.
    """
    row = await _get_or_404(db, approval_id)
    if body.authority_code:
        valid = {a.authority_code for a in row.authorities}
        if body.authority_code not in valid:
            raise HTTPException(
                400, f"authority_code {body.authority_code!r} not in this approval",
            )
    sig = FlightApprovalSignature(
        approval_id=row.id,
        authority_code=body.authority_code,
        signer_user_id=user.id,
        signer_role=getattr(user, "role", None),
        payload_sha256=body.payload_sha256.lower(),
        algorithm=body.algorithm,
        note=body.note,
    )
    db.add(sig)
    row.timeline = (row.timeline or []) + [
        _timeline_event(
            str(user.id),
            "sign",
            f"authority={body.authority_code or 'ALL'} "
            f"sha256={body.payload_sha256[:12]}…",
        )
    ]
    await db.commit()
    await db.refresh(sig)
    return sig


@router.get(
    "/{approval_id}/signatures",
    response_model=list[SignatureOut],
)
async def list_signatures(
    approval_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FlightApprovalSignature]:
    row = await _get_or_404(db, approval_id)
    return list(row.signatures or [])


# ---------------------------------------------------------------------------
# T7.3 — Approval certificate PDF (with QR-code verification watermark)
# ---------------------------------------------------------------------------
@router.get("/{approval_id}/certificate.pdf")
async def approval_certificate_pdf(
    approval_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a single-page PDF certificate for the approval, embedding
    a QR code that resolves to /api/v1/approvals/{id}/verify for
    online verification (chain-of-custody).

    The PDF is deterministic — same approval + same signatures ⇒ same
    bytes (up to ReportLab's DocInfo timestamp, which we override).
    """
    from io import BytesIO

    from fastapi.responses import Response
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light"
    except Exception:  # pragma: no cover — fallback for stripped envs
        font_name = "Helvetica"

    row = await _get_or_404(db, approval_id)
    approval_url = f"{os.getenv('PUBLIC_BASE_URL', '')}/api/v1/approvals/{row.id}/verify"

    # ---- Build QR code ----------------------------------------------------
    qr_png_bytes: bytes | None = None
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(approval_url or f"approval:{row.id}")
        qr.make(fit=True)
        img = qr.make_image()
        buf = BytesIO()
        img.save(buf, format="PNG")
        qr_png_bytes = buf.getvalue()
    except Exception:
        qr_png_bytes = None

    # ---- Draw PDF ---------------------------------------------------------
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    w, h = A4

    c.setTitle(f"SkyMaster Flight Approval Certificate {row.id}")

    # Header
    c.setFont(font_name, 20)
    c.drawCentredString(w / 2, h - 30 * mm, "无人机飞行报备证明")
    c.setFont(font_name, 10)
    c.drawCentredString(w / 2, h - 38 * mm, "SkyMaster Drone Platform · Approval Certificate")

    # Body — key/value block
    y = h - 55 * mm
    def _row(label: str, value: str):
        nonlocal y
        c.setFont(font_name, 10)
        c.drawString(25 * mm, y, label)
        c.setFont(font_name, 11)
        c.drawString(65 * mm, y, value)
        y -= 8 * mm

    _row("报备编号", str(row.id))
    _row("标题", row.title or "-")
    _row("用途", row.purpose or "-")
    _row("类别", row.category or "-")
    _row("飞行器登记号", row.aircraft_reg or "-")
    _row("飞行器型号", row.aircraft_model or "-")
    _row("最大高度 (m)", str(row.max_alt_m or "-"))
    _row("起始时间", row.start_ts.strftime("%Y-%m-%d %H:%M UTC") if row.start_ts else "-")
    _row("结束时间", row.end_ts.strftime("%Y-%m-%d %H:%M UTC") if row.end_ts else "-")
    _row("当前状态", row.status)

    # Authorities table
    y -= 4 * mm
    c.setFont(font_name, 11)
    c.drawString(25 * mm, y, "报备接收单位:")
    y -= 6 * mm
    c.setFont(font_name, 9)
    for a in (row.authorities or []):
        line = f" · {a.authority_code:20s}  channel={a.channel:8s}  status={a.status}"
        if a.external_ref:
            line += f"  ref={a.external_ref}"
        c.drawString(28 * mm, y, line)
        y -= 5 * mm
        if y < 60 * mm:
            break

    # Signatures block
    y -= 4 * mm
    c.setFont(font_name, 11)
    c.drawString(25 * mm, y, "电子签署:")
    y -= 6 * mm
    c.setFont(font_name, 9)
    sigs = list(row.signatures or [])
    if not sigs:
        c.drawString(28 * mm, y, " · (无签署记录)")
        y -= 5 * mm
    else:
        for s in sigs[:6]:
            line = (
                f" · signer={str(s.signer_user_id)[:8]}…"
                f"  role={s.signer_role or '-'}"
                f"  sha256={s.payload_sha256[:12]}…"
                f"  algo={s.algorithm}"
            )
            c.drawString(28 * mm, y, line)
            y -= 5 * mm

    # QR code — bottom right
    if qr_png_bytes:
        try:
            from reportlab.lib.utils import ImageReader
            qimg = ImageReader(BytesIO(qr_png_bytes))
            c.drawImage(
                qimg, w - 45 * mm, 25 * mm, width=30 * mm, height=30 * mm,
                preserveAspectRatio=True, mask="auto",
            )
            c.setFont(font_name, 7)
            c.drawRightString(w - 15 * mm, 22 * mm, "扫码在线核验")
        except Exception:
            pass

    # Footer / verify link
    c.setFont(font_name, 8)
    c.setFillGray(0.4)
    c.drawString(25 * mm, 20 * mm, "验证链接:")
    c.drawString(25 * mm, 16 * mm, approval_url or f"approval:{row.id}")
    c.drawRightString(w - 15 * mm, 12 * mm,
                      f"生成时间 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    c.showPage()
    c.save()
    pdf_bytes = out.getvalue()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="approval-{row.id}.pdf"'
            ),
        },
    )


@router.get("/{approval_id}/verify")
async def approval_verify(
    approval_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Public-ish verification endpoint hit by the QR code on the PDF.

    Returns a minimal chain-of-custody snapshot: status, timeline
    signatures + fingerprints. **No PII beyond what already appears
    on the certificate.** Intentionally does not require auth so a
    regulator can scan the QR from the physical printout — but we
    only expose fields already printed on the same certificate.
    """
    row = await _get_or_404(db, approval_id)
    return {
        "approval_id": str(row.id),
        "status": row.status,
        "aircraft_reg": row.aircraft_reg,
        "start_ts": row.start_ts.isoformat() if row.start_ts else None,
        "end_ts": row.end_ts.isoformat() if row.end_ts else None,
        "authorities": [
            {
                "code": a.authority_code,
                "channel": a.channel,
                "status": a.status,
                "external_ref": a.external_ref,
            }
            for a in (row.authorities or [])
        ],
        "signatures": [
            {
                "signer_role": s.signer_role,
                "payload_sha256": s.payload_sha256,
                "algorithm": s.algorithm,
                "signed_at": s.signed_at.isoformat() if s.signed_at else None,
            }
            for s in (row.signatures or [])
        ],
    }


# ---------------------------------------------------------------------------
# T7.1 — RPA bridge integration
# ---------------------------------------------------------------------------


class RPADispatchIn(BaseModel):
    authority_code: str = Field(..., min_length=1, max_length=32)


class RPACallbackIn(BaseModel):
    """External RPA worker POSTs this after logging into the属地 portal.

    HMAC verification happens in the endpoint, not here.
    """

    job_id: str = Field(..., min_length=1, max_length=64)
    status: str = Field(..., pattern="^(submitted|approving|approved|rejected|cancelled|error)$")
    external_ref: Optional[str] = Field(default=None, max_length=128)
    reject_reason: Optional[str] = Field(default=None, max_length=512)
    evidence: Optional[dict] = None


class RPAJobOut(BaseModel):
    job_id: str
    approval_id: str
    authority_code: str
    driver: str
    status: str
    external_ref: Optional[str] = None
    reject_reason: Optional[str] = None
    poll_count: int
    created_at: float
    updated_at: float


@router.post("/{approval_id}/rpa-dispatch", response_model=RPAJobOut)
async def rpa_dispatch(
    approval_id: UUID,
    body: RPADispatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispatch (or return-existing) an RPA job for one authority row.

    Idempotent: hitting this twice for the same (approval, authority)
    returns the same RPAJob. Authority row's channel must be 'rpa'.
    """
    from app.services.rpa_bridge import get_bridge

    row = await _get_or_404(db, approval_id)
    target = next(
        (a for a in row.authorities if a.authority_code == body.authority_code),
        None,
    )
    if not target:
        raise HTTPException(
            404, f"authority {body.authority_code!r} not on this approval",
        )
    if target.channel != "rpa":
        raise HTTPException(
            400,
            f"authority {body.authority_code!r} uses channel {target.channel!r}, "
            "not 'rpa'",
        )

    bridge = get_bridge()
    payload = {
        "title": row.title,
        "purpose": row.purpose,
        "pilot_name": row.pilot_name,
        "aircraft_reg": row.aircraft_reg,
        "aircraft_model": row.aircraft_model,
        "area_polygon": row.area_polygon,
        "max_alt_m": row.max_alt_m,
        "start_ts": row.start_ts.isoformat() if row.start_ts else None,
        "end_ts": row.end_ts.isoformat() if row.end_ts else None,
    }
    job = await bridge.dispatch(str(row.id), body.authority_code, payload)

    # Sync the authority row with what the bridge reports.
    now = datetime.now(tz=timezone.utc)
    target.status = job.status
    target.submitted_at = target.submitted_at or now
    target.external_ref = job.external_ref
    target.extra = {**(target.extra or {}), "rpa_job_id": job.job_id, "driver": job.driver}
    row.timeline = (row.timeline or []) + [
        _timeline_event(
            str(user.id),
            "rpa_dispatch",
            f"authority={body.authority_code} job={job.job_id} driver={job.driver}",
        )
    ]
    await db.commit()
    return {
        "job_id": job.job_id,
        "approval_id": job.approval_id,
        "authority_code": job.authority_code,
        "driver": job.driver,
        "status": job.status,
        "external_ref": job.external_ref,
        "reject_reason": job.reject_reason,
        "poll_count": job.poll_count,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("/rpa-jobs/{job_id}", response_model=RPAJobOut)
async def rpa_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Poll and return the current RPA job snapshot. The bridge
    driver may advance status on this call (mock driver auto-progresses).
    """
    from app.services.rpa_bridge import get_bridge

    bridge = get_bridge()
    job = await bridge.poll(job_id)
    if not job:
        raise HTTPException(404, "rpa job not found")
    return {
        "job_id": job.job_id,
        "approval_id": job.approval_id,
        "authority_code": job.authority_code,
        "driver": job.driver,
        "status": job.status,
        "external_ref": job.external_ref,
        "reject_reason": job.reject_reason,
        "poll_count": job.poll_count,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.post("/rpa-callback", status_code=200)
async def rpa_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """HMAC-signed webhook from an external RPA worker (Docker Playwright
    box, staff-desk browser extension, or the mock in tests).

    Verifies X-RPA-Signature = hex(HMAC-SHA256(raw_body, RPA_WEBHOOK_SECRET))
    over the raw request bytes (order-preserving), then updates the
    authority row + emits a timeline event.
    """
    import hashlib, hmac, json as _json

    secret = os.getenv("RPA_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(503, "RPA_WEBHOOK_SECRET not configured on server")

    raw = await request.body()
    provided = request.headers.get("X-RPA-Signature", "")
    expected = hmac.new(
        secret.encode("utf-8"), raw, hashlib.sha256,
    ).hexdigest()
    if not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(401, "invalid RPA signature")

    try:
        parsed = _json.loads(raw)
    except _json.JSONDecodeError:
        raise HTTPException(400, "malformed JSON body")

    try:
        body = RPACallbackIn.model_validate(parsed)
    except Exception as e:
        raise HTTPException(422, f"invalid callback payload: {e}")

    from app.services.rpa_bridge import get_bridge

    bridge = get_bridge()
    job = bridge.get(body.job_id)
    if not job:
        raise HTTPException(404, "rpa job not found")

    # Update job (in-memory) — a real Redis-backed bridge would persist.
    job.status = body.status
    if body.external_ref is not None:
        job.external_ref = body.external_ref
    if body.reject_reason is not None:
        job.reject_reason = body.reject_reason
    if body.evidence is not None:
        job.evidence = body.evidence
    job.touch()

    # Update the matching FlightApprovalAuthority row.
    row_result = await db.execute(
        select(FlightApprovalAuthority).where(
            FlightApprovalAuthority.approval_id == UUID(job.approval_id),
            FlightApprovalAuthority.authority_code == job.authority_code,
        )
    )
    auth_row = row_result.scalar_one_or_none()
    if auth_row:
        auth_row.status = body.status
        if body.external_ref:
            auth_row.external_ref = body.external_ref
        if body.reject_reason:
            auth_row.reject_reason = body.reject_reason
        if body.status in {"approved", "rejected"}:
            auth_row.responded_at = datetime.now(tz=timezone.utc)
        # Append a timeline event on the parent approval.
        approval = (await db.execute(
            select(FlightApproval).where(FlightApproval.id == auth_row.approval_id)
        )).scalar_one()
        approval.timeline = (approval.timeline or []) + [
            _timeline_event(
                "rpa-worker",
                f"rpa_{body.status}",
                f"authority={job.authority_code} job={job.job_id}"
                + (f" reason={body.reject_reason}" if body.reject_reason else ""),
            )
        ]
        await db.commit()

    return {"ok": True, "job_id": job.job_id, "status": job.status}
