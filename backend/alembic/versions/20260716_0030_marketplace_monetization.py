"""E2.7 · Model marketplace monetization — pricing + purchase orders.

Revision ID: 20260716_0030
Revises: 20260716_0029
Create Date: 2026-07-16

Rationale
=========
Roadmap §3.15 lists ``model_marketplace`` as a v2.0 P0 feature. We
already have listings/versions/deployments/reviews/favorites/usage
events (test_model_marketplace*.py — 8 files pass). The gap is the
**monetization layer**: pricing plans + purchase orders + revenue
splits, so vendors can actually get paid.

Design
------
* ``model_listing_price``: one row per (listing, plan_code). A single
  listing can have multiple simultaneous pricing plans, e.g. free-trial,
  monthly-subscription, per-inference-metered. Historic prices are
  soft-deleted (retired=True) instead of overwritten.
* ``model_purchase_order``: one row per {org, listing, plan} purchase.
  status: pending -> paid | cancelled | refunded.
* ``platform_fee_bps`` on the price row lets us split revenue between
  platform (skymaster) and vendor (uploader) at charge time.

Deliberately kept off-topic from RBAC/auth — that lives in the
existing auth stack. Purchase actor is captured via ``user_id``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260716_0030"
down_revision = "20260716_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_listing_price",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "listing_id", postgresql.UUID(as_uuid=True),
            nullable=False, index=True,
        ),
        sa.Column("plan_code", sa.String(64), nullable=False),
        sa.Column("plan_name", sa.String(128), nullable=False),
        sa.Column(
            "billing_mode", sa.String(24), nullable=False,
        ),
        sa.Column(
            "unit_price_cny_cents", sa.Integer(), nullable=False,
        ),
        sa.Column(
            "included_quota", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "billing_cycle_days", sa.Integer(), nullable=True,
        ),
        sa.Column(
            "platform_fee_bps", sa.Integer(),
            nullable=False, server_default="1500",
        ),
        sa.Column(
            "currency", sa.String(3), nullable=False,
            server_default="CNY",
        ),
        sa.Column(
            "retired", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "billing_mode IN ('one_off','subscription','metered','free_trial')",
            name="ck_price_billing_mode",
        ),
        sa.CheckConstraint(
            "unit_price_cny_cents >= 0",
            name="ck_price_nonnegative",
        ),
        sa.CheckConstraint(
            "platform_fee_bps >= 0 AND platform_fee_bps <= 10000",
            name="ck_price_fee_bps_range",
        ),
    )
    op.create_index(
        "ix_model_price_listing_active",
        "model_listing_price",
        ["listing_id", "retired"],
    )
    op.create_unique_constraint(
        "uq_model_price_listing_plan",
        "model_listing_price",
        ["listing_id", "plan_code"],
    )

    op.create_table(
        "model_purchase_order",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id", postgresql.UUID(as_uuid=True),
            nullable=False, index=True,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "listing_id", postgresql.UUID(as_uuid=True),
            nullable=False, index=True,
        ),
        sa.Column(
            "price_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("plan_code", sa.String(64), nullable=False),
        sa.Column("billing_mode", sa.String(24), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("total_cny_cents", sa.Integer(), nullable=False),
        sa.Column(
            "platform_fee_cny_cents", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "vendor_payout_cny_cents", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("external_ref", sa.String(128), nullable=True),
        sa.Column(
            "activated_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "expires_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','paid','cancelled','refunded')",
            name="ck_purchase_status",
        ),
        sa.CheckConstraint(
            "units >= 1",
            name="ck_purchase_units_positive",
        ),
    )
    op.create_index(
        "ix_model_purchase_org_created",
        "model_purchase_order",
        ["org_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_purchase_org_created", table_name="model_purchase_order")
    op.drop_table("model_purchase_order")
    op.drop_constraint("uq_model_price_listing_plan", "model_listing_price", type_="unique")
    op.drop_index("ix_model_price_listing_active", table_name="model_listing_price")
    op.drop_table("model_listing_price")
