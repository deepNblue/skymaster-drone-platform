"""R22 · Audit log export API.

Endpoints (all require the ``audit.export`` action → audit officer only).

* ``GET /audit/export/csv``     — full CSV download.
* ``GET /audit/export/gbft``    — GB/T 20945 JSONL download.
* ``GET /audit/export/preview`` — first N rows as JSON (审计员在导出前预览).
* ``GET /audit/integrity``      — chain integrity report (no export payload,
                                    audit officer + security officer 可读).

All exports write an ``audit.export`` action row to audit_logs so we have a
paper trail of who pulled what.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services import audit_export as _svc
from app.services.audit_export import ExportFilter
from app.services.officer_matrix import require_action


router = APIRouter(prefix="/audit", tags=["audit"])


# --------- Filter parser ---------------------------------------------------


def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        # Accept "2026-07-13T00:00:00" and "2026-07-13T00:00:00Z"
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(400, f"invalid datetime {v!r}: {e}")


def _parse_uuid(v: Optional[str]) -> Optional[UUID]:
    if not v:
        return None
    try:
        return UUID(v)
    except ValueError as e:
        raise HTTPException(400, f"invalid uuid {v!r}: {e}")


def _build_filter(
    ts_from: Optional[str],
    ts_to: Optional[str],
    actor_role: Optional[str],
    action: Optional[str],
    actor_id: Optional[str],
    limit: int,
) -> ExportFilter:
    return ExportFilter(
        ts_from=_parse_dt(ts_from),
        ts_to=_parse_dt(ts_to),
        actor_role=actor_role,
        action=action,
        actor_id=_parse_uuid(actor_id),
        limit=limit,
    )


# --------- Helpers ---------------------------------------------------------


def _fname(prefix: str, ext: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"skymaster-audit-{prefix}-{ts}.{ext}"


async def _record_export(
    db: AsyncSession, user: User, fmt: str, flt: ExportFilter, size: int
) -> None:
    """Write an audit.export row so the export itself is auditable."""
    entry = AuditLog(
        actor_id=user.id,
        actor_role=user.role,
        action="audit.export",
        resource=f"format={fmt}",
        diff={
            "format": fmt,
            "size_bytes": size,
            "filter": {
                "ts_from": flt.ts_from.isoformat() if flt.ts_from else None,
                "ts_to": flt.ts_to.isoformat() if flt.ts_to else None,
                "actor_role": flt.actor_role,
                "action": flt.action,
            },
        },
    )
    db.add(entry)
    await db.commit()


# --------- CSV / GBFT downloads --------------------------------------------


@router.get("/export/csv", dependencies=[Depends(require_action("audit.export"))])
async def export_csv(
    ts_from: Optional[str] = Query(None),
    ts_to: Optional[str] = Query(None),
    actor_role: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    limit: int = Query(_svc.MAX_ROWS_PER_EXPORT, ge=1, le=_svc.MAX_ROWS_PER_EXPORT),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_action("audit.export")),
) -> Response:
    flt = _build_filter(ts_from, ts_to, actor_role, action, actor_id, limit)
    body = await _svc.export_csv(db, flt)
    await _record_export(db, user, "csv", flt, len(body))
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_fname("export", "csv")}"'},
    )


@router.get("/export/gbft", dependencies=[Depends(require_action("audit.export"))])
async def export_gbft(
    ts_from: Optional[str] = Query(None),
    ts_to: Optional[str] = Query(None),
    actor_role: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    limit: int = Query(_svc.MAX_ROWS_PER_EXPORT, ge=1, le=_svc.MAX_ROWS_PER_EXPORT),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_action("audit.export")),
) -> Response:
    flt = _build_filter(ts_from, ts_to, actor_role, action, actor_id, limit)
    body = await _svc.export_gbft(db, flt)
    await _record_export(db, user, "gbft", flt, len(body))
    return Response(
        content=body,
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_fname("export", "gbft.jsonl")}"'},
    )


# --------- Preview + integrity report --------------------------------------


class PreviewOut(BaseModel):
    total: int
    sample: list[dict]


@router.get("/export/preview", response_model=PreviewOut)
async def export_preview(
    ts_from: Optional[str] = Query(None),
    ts_to: Optional[str] = Query(None),
    actor_role: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_action("audit.read")),
) -> PreviewOut:
    flt = _build_filter(ts_from, ts_to, actor_role, action, actor_id, limit)
    from app.services.audit_export import _row_to_public, _stream_rows

    rows = []
    async for r in _stream_rows(db, flt):
        rows.append(_row_to_public(r))
    return PreviewOut(total=len(rows), sample=rows)


class IntegrityOut(BaseModel):
    total: int
    hash_chain_ok: bool
    hash_chain_break_at: Optional[int]
    signed_count: int
    unsigned_count: int


@router.get("/integrity", response_model=IntegrityOut)
async def audit_integrity(
    ts_from: Optional[str] = Query(None),
    ts_to: Optional[str] = Query(None),
    actor_role: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_action("audit.chain_verify")),
) -> IntegrityOut:
    flt = _build_filter(ts_from, ts_to, actor_role, action, None, _svc.MAX_ROWS_PER_EXPORT)
    rep = await _svc.integrity_report(db, flt)
    return IntegrityOut(
        total=rep.total,
        hash_chain_ok=rep.hash_chain_ok,
        hash_chain_break_at=rep.hash_chain_break_at,
        signed_count=rep.signed_count,
        unsigned_count=rep.unsigned_count,
    )
