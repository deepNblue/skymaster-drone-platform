"""External platform reverse access models for v2.3 E8.

v2.3 E8: 第三方平台反向接入 — DJI 司空 2 / 极飞 / 道通 等外部平台
可以使用 SkyMaster 做合规报备，SkyMaster 对外暴露 Approval-as-a-Service API.

Key concepts:
- `ExternalTenant` — registered external platform, gets AK/SK for auth
- `ExternalApproval` — approval created by external tenant, tracks mapping to external ID
- `Webhook` — callback to external platform when approval status changes
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ExternalTenant(Base):
    """Registered external platform tenant that uses SkyMaster Approval-as-a-Service.

    Each tenant gets AK/SK for authentication, quota, and billing.
    """

    __tablename__ = "external_tenants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(128), nullable=False)
    access_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    secret_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    quota_approvals_per_month: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    billing_price_cents_per_approval: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    webhook_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class ExternalApproval(Base):
    """An approval created by an external platform tenant through the API.

    Stores the external platform's own ID for mapping back.
    """

    __tablename__ = "external_approvals"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("external_tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    internal_approval_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("flight_approvals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)  # full incoming request
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    webhook_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_webhook_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class ExternalTenantQuotaUsage(Base):
    """Monthly quota usage tracking for external tenants."""

    __tablename__ = "external_tenant_quota_usage"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("external_tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year_month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # "2026-07"
    approvals_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_billing_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
