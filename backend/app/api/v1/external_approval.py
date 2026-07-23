"""External platform reverse approval API — v2.3 E8.

Third-party platforms (DJI 司空 2 / 极飞 / 道通) can use SkyMaster
to handle flight approval through the open API, and get webhook callback
when status changes.

Authentication: AK/SK in query parameters or Authorization header.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.external_platform import (
    ExternalTenant,
    ExternalApproval,
    ExternalTenantQuotaUsage,
)
from app.models.flight_approval import FlightApproval


router = APIRouter(prefix="/external-approval", tags=["external-approval"])


# ---------- Auth -------------------------------------------------------------


async def verify_ak_sk(
    access_key: str,
    signature: str,
    body: str,
    db: AsyncSession,
) -> Optional[ExternalTenant]:
    """Verify AK/SK authentication."""
    tenant = (
        await db.execute(
            select(ExternalTenant).where(
                ExternalTenant.access_key == access_key,
                ExternalTenant.enabled == True,
            )
        )
    ).scalar_one_or_none()
    if tenant is None:
        return None
    expected = hmac.new(
        tenant.secret_key_hash.encode(),
        body.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    return tenant


async def check_quota(
    tenant: ExternalTenant,
    db: AsyncSession,
) -> bool:
    """Check if tenant has remaining quota for this month."""
    from datetime import datetime
    year_month = f"{datetime.utcnow().year}-{datetime.utcnow().month:02d}"
    quota = (
        await db.execute(
            select(ExternalTenantQuotaUsage).where(
                ExternalTenantQuotaUsage.external_tenant_id == tenant.id,
                ExternalTenantQuotaUsage.year_month == year_month,
            )
        )
    ).scalar_one_or_none()
    if quota is None:
        # No usage yet, quota ok
        return True
    return quota.approvals_used < tenant.quota_approvals_per_month


async def increment_quota(
    tenant: ExternalTenant,
    db: AsyncSession,
    price_cents: int,
) -> None:
    """Increment usage quota for this month."""
    from datetime import datetime
    year_month = f"{datetime.utcnow().year}-{datetime.utcnow().month:02d}"
    quota = (
        await db.execute(
            select(ExternalTenantQuotaUsage).where(
                ExternalTenantQuotaUsage.external_tenant_id == tenant.id,
                ExternalTenantQuotaUsage.year_month == year_month,
            )
        )
    ).scalar_one_or_none()
    if quota is None:
        quota = ExternalTenantQuotaUsage(
            external_tenant_id=tenant.id,
            year_month=year_month,
            approvals_used=1,
            total_billing_cents=price_cents,
        )
        db.add(quota)
    else:
        quota.approvals_used += 1
        quota.total_billing_cents += price_cents
    await db.commit()


# ---------- Schemas ---------------------------------------------------------


class CreateExternalApprovalRequest(BaseModel):
    external_id: str = Field(description="ID on external platform")
    payload: dict = Field(description="Full approval payload")
    # We extract common fields from payload for our processing
    province: str
    city: str
    drone_info: dict
    mission_info: dict


class CreateExternalApprovalResponse(BaseModel):
    id: str
    external_id: str
    status: str
    message: str = ""


class GetStatusResponse(BaseModel):
    id: str
    external_id: str
    internal_status: Optional[str]
    last_webhook_sent: Optional[str]
    created_at: str


# ---------- Endpoints -------------------------------------------------------


@router.post("/", response_model=CreateExternalApprovalResponse)
async def create_external_approval(
    req: CreateExternalApprovalRequest,
    access_key: str = Query(..., description="Access Key"),
    signature: str = Query(..., description="Request signature (HMAC-SHA256 of body with SK)"),
    db: AsyncSession = Depends(get_db),
) -> CreateExternalApprovalResponse:
    """Create a new flight approval request from external platform.

    Authentication: ?access_key=...&signature=...
    """
    # Authenticate
    import json
    body = json.dumps(req.model_dump(), separators=(",", ":"))
    tenant = await verify_ak_sk(access_key, signature, body, db)
    if tenant is None:
        raise HTTPException(401, "invalid access key or signature")

    # Check quota
    if not await check_quota(tenant, db):
        raise HTTPException(429, "monthly quota exceeded")

    # Check duplicate external_id
    existing = (
        await db.execute(
            select(ExternalApproval).where(
                ExternalApproval.external_tenant_id == tenant.id,
                ExternalApproval.external_id == req.external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return CreateExternalApprovalResponse(
            id=str(existing.id),
            external_id=existing.external_id,
            status=existing.last_status or "processed",
            message="already exists",
        )

    # Create external approval record
    ext_approval = ExternalApproval(
        external_tenant_id=tenant.id,
        external_id=req.external_id,
        payload=req.payload,
        processed=False,
    )
    db.add(ext_approval)

    # TODO(v2.3.1): actually create internal FlightApproval using city template
    # For MVP: just record the external request, processed manually later
    # async processing picks it up

    # Increment quota
    await increment_quota(tenant, db, tenant.billing_price_cents_per_approval)
    await db.commit()
    await db.refresh(ext_approval)

    return CreateExternalApprovalResponse(
        id=str(ext_approval.id),
        external_id=req.external_id,
        status="received",
        message="approval request queued",
    )


@router.get("/{external_id}", response_model=GetStatusResponse)
async def get_approval_status(
    external_id: str,
    access_key: str = Query(..., description="Access Key"),
    signature: str = Query(..., description="Signature"),
    db: AsyncSession = Depends(get_db),
) -> GetStatusResponse:
    """Get current status of an external approval."""
    # Authenticate
    body = external_id  # signature over external_id for GET
    tenant = await verify_ak_sk(access_key, signature, body, db)
    if tenant is None:
        raise HTTPException(401, "invalid access key or signature")

    approval = (
        await db.execute(
            select(ExternalApproval).where(
                ExternalApproval.external_tenant_id == tenant.id,
                ExternalApproval.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(404, "approval not found")

    return GetStatusResponse(
        id=str(approval.id),
        external_id=approval.external_id,
        internal_status=approval.last_status,
        last_webhook_sent= None,  # TODO
        created_at=approval.created_at.isoformat(),
    )


@router.get("/tenants/me", response_model=dict)
async def get_tenant_info(
    access_key: str = Query(...),
    signature: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get current tenant info and quota status for this month."""
    from datetime import datetime
    body = "me"
    tenant = await verify_ak_sk(access_key, signature, body, db)
    if tenant is None:
        raise HTTPException(401, "invalid access key or signature")

    year_month = f"{datetime.utcnow().year}-{datetime.utcnow().month:02d}"
    quota = (
        await db.execute(
            select(ExternalTenantQuotaUsage).where(
                ExternalTenantQuotaUsage.external_tenant_id == tenant.id,
                ExternalTenantQuotaUsage.year_month == year_month,
            )
        )
    ).scalar_one_or_none()

    used = quota.approvals_used if quota else 0
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "quota_total": tenant.quota_approvals_per_month,
        "quota_used": used,
        "quota_remaining": tenant.quota_approvals_per_month - used,
        "billing_cents_this_month": quota.total_billing_cents if quota else 0,
    }
