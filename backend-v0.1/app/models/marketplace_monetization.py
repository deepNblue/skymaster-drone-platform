"""E2.7 · Marketplace monetization models — pricing & purchase orders.

Sibling of app/models/model_marketplace.py (listings/versions/etc).
These two tables carry monetary state; see migration
``20260716_0030_marketplace_monetization.py`` for the design.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


VALID_BILLING_MODES = frozenset({
    "one_off", "subscription", "metered", "free_trial",
})
VALID_PURCHASE_STATUSES = frozenset({
    "pending", "paid", "cancelled", "refunded",
})


class ModelListingPrice(Base):
    """Pricing plan for a listing.

    One row per (listing, plan_code). Retire (soft-delete) rather than
    overwrite so historical purchase orders keep their price context.
    """
    __tablename__ = "model_listing_price"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    plan_code: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(128), nullable=False)
    billing_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    unit_price_cny_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    included_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    billing_cycle_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    platform_fee_bps: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1500,  # 15% default
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="CNY",
    )
    retired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    __table_args__ = (
        CheckConstraint(
            "billing_mode IN ('one_off','subscription','metered','free_trial')",
            name="ck_price_billing_mode",
        ),
        CheckConstraint(
            "unit_price_cny_cents >= 0",
            name="ck_price_nonnegative",
        ),
        CheckConstraint(
            "platform_fee_bps >= 0 AND platform_fee_bps <= 10000",
            name="ck_price_fee_bps_range",
        ),
    )


class ModelPurchaseOrder(Base):
    __tablename__ = "model_purchase_order"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    price_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    plan_code: Mapped[str] = mapped_column(String(64), nullable=False)
    billing_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    units: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    total_cny_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_cny_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    vendor_payout_cny_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','paid','cancelled','refunded')",
            name="ck_purchase_status",
        ),
        CheckConstraint(
            "units >= 1",
            name="ck_purchase_units_positive",
        ),
    )
