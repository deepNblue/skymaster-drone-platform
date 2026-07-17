"""R23 · CIIO 自评 API。

Endpoints
---------

* ``GET /ciio/status``           — JSON snapshot (审计员/安全员/管理员均可读)
* ``GET /ciio/report.md``        — 下载 markdown 自评报告
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services import ciio_assessment as svc


router = APIRouter(prefix="/ciio", tags=["ciio"])


def _require_officer_or_admin(user: User) -> None:
    """CIIO 报告面向 admin 与三员开放，普通 user 禁止。"""
    from fastapi import HTTPException

    allowed = {"admin", "system_officer", "security_officer", "audit_officer"}
    if user.role not in allowed:
        raise HTTPException(403, "role forbidden")


@router.get("/status")
async def ciio_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_officer_or_admin(user)
    rep = await svc.run_all_checks(db)
    return rep.to_dict()


@router.get("/report.md")
async def ciio_report_md(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    _require_officer_or_admin(user)
    rep = await svc.run_all_checks(db)
    body = svc.render_markdown(rep).encode("utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ciio-self-assessment-{ts}.md"',
        },
    )
