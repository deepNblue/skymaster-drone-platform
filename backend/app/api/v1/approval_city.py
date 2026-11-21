"""City-specific approval templates API for AAS v2.3 production.

Implements:
- GET /approval-city/templates — list enabled templates
- GET /approval-city/{city} — get template for city
- POST /approval-city/parse-receipt — parse incoming email and update status
- Admin: create/update templates
"""
from __future__ import annotations

from typing import Annotated, Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.approval_city_templates import (
    CityApprovalTemplate,
    ApprovalStatusReceipt,
)
from app.models.flight_approval import FlightApproval
from app.models.user import User


router = APIRouter(prefix="/approval-city", tags=["approval-city"])


# ---------- Schemas ---------------------------------------------------------

class CityTemplateOut(BaseModel):
    id: UUID
    province: str
    city: str
    city_adcode: Optional[str]
    enabled: bool
    required_fields: List[str]
    field_labels: Optional[dict]
    submission_channel: str
    target_email: Optional[str]
    email_subject_template: Optional[str]
    email_body_template: Optional[str]
    last_tested_at: Optional[str]

    model_config = {"from_attributes": True}


class CreateTemplateRequest(BaseModel):
    province: str
    city: str
    city_adcode: Optional[str] = None
    required_fields: List[str]
    field_labels: Optional[dict] = None
    submission_channel: str = "email"
    target_email: Optional[str] = None
    email_subject_template: Optional[str] = None
    email_body_template: Optional[str] = None
    approve_patterns: Optional[List[str]] = None
    reject_patterns: Optional[List[str]] = None
    notes: Optional[str] = None


class ParseReceiptRequest(BaseModel):
    approval_id: UUID
    source: str = "email"
    subject: Optional[str]
    body: Optional[str]


# ---------- Endpoints -------------------------------------------------------


@router.get("/templates", response_model=List[CityTemplateOut])
async def list_enabled_templates(
    province: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CityTemplateOut]:
    """List all enabled city templates (optionally filtered by province)."""
    query = select(CityApprovalTemplate).where(CityApprovalTemplate.enabled == True)
    if province:
        query = query.where(CityApprovalTemplate.province == province)
    query = query.order_by(CityApprovalTemplate.province, CityApprovalTemplate.city)
    result = await db.execute(query)
    items = result.scalars().all()
    return [CityTemplateOut.model_validate(t) for t in items]


@router.get("/template-by-city/{province}/{city}", response_model=CityTemplateOut)
async def get_template_for_city(
    province: str,
    city: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CityTemplateOut:
    """Get template for specific province + city (exact match)."""
    template = (
        await db.execute(
            select(CityApprovalTemplate).where(
                CityApprovalTemplate.province == province,
                CityApprovalTemplate.city == city,
                CityApprovalTemplate.enabled == True,
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(404, "no enabled template for this city")
    return CityTemplateOut.model_validate(template)


@router.post("/templates", response_model=CityTemplateOut)
async def create_template(
    req: CreateTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CityTemplateOut:
    """Create new city template (admin only)."""
    if current_user.role not in ("admin", "system_officer"):
        raise HTTPException(403, "admin only")

    # Check duplicate
    existing = (
        await db.execute(
            select(CityApprovalTemplate).where(
                CityApprovalTemplate.province == req.province,
                CityApprovalTemplate.city == req.city,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(400, "template for this city already exists")

    template = CityApprovalTemplate(
        province=req.province,
        city=req.city,
        city_adcode=req.city_adcode,
        required_fields=req.required_fields,
        field_labels=req.field_labels,
        submission_channel=req.submission_channel,
        target_email=req.target_email,
        email_subject_template=req.email_subject_template,
        email_body_template=req.email_body_template,
        approve_patterns=req.approve_patterns,
        reject_patterns=req.reject_patterns,
        notes=req.notes,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return CityTemplateOut.model_validate(template)


def match_status(
    text: str,
    approve_patterns: Optional[list[str]],
    reject_patterns: Optional[list[str]],
) -> str | None:
    """Match text against patterns to guess approval status."""
    text_lower = text.lower()
    if approve_patterns:
        for pat in approve_patterns:
            if pat.lower() in text_lower:
                return "approved"
    if reject_patterns:
        for pat in reject_patterns:
            if pat.lower() in text_lower:
                return "rejected"
    return None


@router.post("/parse-receipt", response_model=dict[str, Optional[str]])
async def parse_and_update_receipt(
    req: ParseReceiptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Optional[str]]:
    """Parse receipt email and update approval status automatically."""
    approval = (
        await db.execute(
            select(FlightApproval).where(FlightApproval.id == req.approval_id)
        )
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(404, "approval not found")

    # Get city template from approval city
    if not approval.city:
        raise HTTPException(400, "approval has no city field")

    # Find template
    template = (
        await db.execute(
            select(CityApprovalTemplate).where(
                CityApprovalTemplate.city == approval.city,
                CityApprovalTemplate.enabled == True,
            )
        )
    ).scalar_one_or_none()

    combined_text = ""
    if req.subject:
        combined_text += req.subject + " "
    if req.body:
        combined_text += req.body

    parsed_status: Optional[str] = None
    if template:
        parsed_status = match_status(
            combined_text,
            template.approve_patterns,
            template.reject_patterns,
        )

    # Save receipt even if we didn't parse a status
    receipt = ApprovalStatusReceipt(
        approval_id=req.approval_id,
        city_template_id=template.id if template else None,
        source=req.source,
        parsed_status=parsed_status or "received",
        raw_subject=req.subject,
        raw_body=req.body,
        manually_updated_by=current_user.id,
    )
    db.add(receipt)

    # If we parsed a definitive status, update the approval
    if parsed_status in ("approved", "rejected"):
        approval.status = parsed_status
        await db.commit()

    return {
        "parsed_status": parsed_status,
        "template_used": str(template.id) if template else None,
    }
