"""E2.5 · Flight approval template service — CRUD + apply.

The interesting method is ``apply_to_new_approval``: it takes a
template + user-supplied delta (start_ts/end_ts, optional polygon
override) and stamps out a real FlightApproval row + its
authorities. That row can then flow through the existing
approvals state machine untouched — no fork of business logic.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval_template import ApprovalTemplate, VALID_CATEGORIES
from app.models.flight_approval import (
    FlightApproval, FlightApprovalAuthority,
)


class TemplateError(Exception):
    """Domain errors, mapped 400/403/404 at the REST layer."""


# ============================================================ CRUD ==


async def create_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    author_user_id: uuid.UUID,
    name: str,
    category: str,
    purpose: str | None = None,
    pilot_name: str | None = None,
    pilot_license: str | None = None,
    aircraft_reg: str | None = None,
    aircraft_model: str | None = None,
    insurance_no: str | None = None,
    max_alt_m: float | None = None,
    min_alt_m: float | None = None,
    default_area_polygon: list | None = None,
    authorities_preset: list[dict[str, Any]] | None = None,
    checklist_json: list[dict[str, Any]] | None = None,
) -> ApprovalTemplate:
    if category not in VALID_CATEGORIES:
        raise TemplateError(f"invalid category: {category}")
    if not name.strip():
        raise TemplateError("template name is required")

    # Normalize authorities_preset.
    presets = list(authorities_preset or [])
    for a in presets:
        if "code" not in a or "name" not in a:
            raise TemplateError(
                "each authority preset must have 'code' and 'name'"
            )

    # Explicit uniqueness check within org (the partial unique index
    # is Postgres-only; enforce here for portability).
    dup = (await db.execute(
        select(ApprovalTemplate).where(
            ApprovalTemplate.org_id == org_id,
            ApprovalTemplate.name == name.strip(),
            ApprovalTemplate.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if dup is not None:
        raise TemplateError(
            f"template name '{name}' already exists in this org"
        )

    row = ApprovalTemplate(
        org_id=org_id,
        author_user_id=author_user_id,
        name=name.strip(),
        category=category,
        purpose=purpose,
        pilot_name=pilot_name,
        pilot_license=pilot_license,
        aircraft_reg=aircraft_reg,
        aircraft_model=aircraft_model,
        insurance_no=insurance_no,
        max_alt_m=max_alt_m,
        min_alt_m=min_alt_m,
        default_area_polygon=default_area_polygon,
        authorities_preset=presets,
        checklist_json=list(checklist_json or []),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise TemplateError(
            f"template name '{name}' already exists in this org"
        ) from exc
    await db.refresh(row)
    return row


async def list_templates(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    category: str | None = None,
    limit: int = 100,
) -> list[ApprovalTemplate]:
    q = select(ApprovalTemplate).where(
        ApprovalTemplate.org_id == org_id,
        ApprovalTemplate.deleted_at.is_(None),
    )
    if category is not None:
        if category not in VALID_CATEGORIES:
            raise TemplateError(f"invalid category filter: {category}")
        q = q.where(ApprovalTemplate.category == category)
    q = q.order_by(
        ApprovalTemplate.apply_count.desc(),
        ApprovalTemplate.created_at.desc(),
    ).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


async def get_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> ApprovalTemplate | None:
    q = select(ApprovalTemplate).where(
        ApprovalTemplate.id == template_id,
        ApprovalTemplate.org_id == org_id,
        ApprovalTemplate.deleted_at.is_(None),
    )
    return (await db.execute(q)).scalar_one_or_none()


async def update_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    patch: dict[str, Any],
) -> ApprovalTemplate:
    row = await get_template(db, org_id=org_id, template_id=template_id)
    if row is None:
        raise TemplateError("template not found")

    ALLOWED = {
        "name", "category", "purpose", "pilot_name", "pilot_license",
        "aircraft_reg", "aircraft_model", "insurance_no",
        "max_alt_m", "min_alt_m", "default_area_polygon",
        "authorities_preset", "checklist_json",
    }
    for k, v in patch.items():
        if k not in ALLOWED:
            continue
        if k == "category" and v not in VALID_CATEGORIES:
            raise TemplateError(f"invalid category: {v}")
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> bool:
    row = await get_template(db, org_id=org_id, template_id=template_id)
    if row is None:
        return False
    row.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ================================================== Apply/Instantiate


async def apply_to_new_approval(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    created_by: uuid.UUID,
    title: str,
    start_ts: datetime,
    end_ts: datetime,
    area_polygon_override: list | None = None,
    max_alt_m_override: float | None = None,
    min_alt_m_override: float | None = None,
) -> FlightApproval:
    """Create a real flight_approval row from a template + a delta.

    Returns the new FlightApproval (status='draft'). The pilot can
    then run the existing submit → route → decide flow untouched.
    """
    template = await get_template(
        db, org_id=org_id, template_id=template_id,
    )
    if template is None:
        raise TemplateError("template not found")

    if start_ts >= end_ts:
        raise TemplateError("start_ts must be earlier than end_ts")

    polygon = area_polygon_override or template.default_area_polygon
    max_alt = max_alt_m_override
    if max_alt is None:
        max_alt = template.max_alt_m
    min_alt = min_alt_m_override
    if min_alt is None:
        min_alt = template.min_alt_m

    approval = FlightApproval(
        tenant_id=org_id,
        created_by=created_by,
        category=template.category,
        title=title.strip(),
        purpose=template.purpose,
        pilot_name=template.pilot_name,
        pilot_license=template.pilot_license,
        aircraft_reg=template.aircraft_reg,
        aircraft_model=template.aircraft_model,
        insurance_no=template.insurance_no,
        area_polygon=polygon,
        max_alt_m=max_alt,
        min_alt_m=min_alt,
        start_ts=start_ts,
        end_ts=end_ts,
        status="draft",
        timeline=[{
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": str(created_by),
            "action": "created_from_template",
            "note": f"template_id={template.id}",
        }],
    )
    db.add(approval)
    await db.flush()  # need approval.id for FK

    for a in template.authorities_preset:
        db.add(FlightApprovalAuthority(
            approval_id=approval.id,
            authority_code=a["code"],
            authority_name=a["name"],
            channel=a.get("channel", "manual"),
            priority=int(a.get("priority", 0)),
            status="pending",
        ))

    template.apply_count = (template.apply_count or 0) + 1
    await db.commit()
    await db.refresh(approval)
    return approval
