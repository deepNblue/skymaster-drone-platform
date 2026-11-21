"""v2.0 R17 — flight_approvals + flight_approval_authorities tables.

Revision ID: 20260710_0011
Revises: 20260710_0010
Create Date: 2026-07-10 07:45:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260710_0011"
down_revision: Union[str, None] = "20260710_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "flight_approvals",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category", sa.String(16), server_default="routine", nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(255), nullable=True),
        sa.Column("pilot_name", sa.String(64), nullable=True),
        sa.Column("pilot_license", sa.String(64), nullable=True),
        sa.Column("aircraft_reg", sa.String(64), nullable=True),
        sa.Column("aircraft_model", sa.String(64), nullable=True),
        sa.Column("insurance_no", sa.String(64), nullable=True),
        sa.Column("area_polygon", postgresql.JSONB, nullable=True),
        sa.Column("max_alt_m", sa.Float(), nullable=True),
        sa.Column("min_alt_m", sa.Float(), nullable=True),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("reject_reason", sa.String(512), nullable=True),
        sa.Column("timeline", postgresql.JSONB, server_default="[]", nullable=True),
        sa.Column("attachments", postgresql.JSONB, server_default="[]", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_flight_approvals_tenant", "flight_approvals", ["tenant_id"])
    op.create_index("ix_flight_approvals_mission", "flight_approvals", ["mission_id"])
    op.create_index("ix_flight_approvals_status", "flight_approvals", ["status"])
    op.create_index("ix_flight_approvals_created", "flight_approvals", ["created_at"])

    op.create_table(
        "flight_approval_authorities",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "approval_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flight_approvals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("authority_code", sa.String(32), nullable=False),
        sa.Column("authority_name", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(16), server_default="manual", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("external_ref", sa.String(128), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.String(512), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extra", postgresql.JSONB, nullable=True),
    )
    op.create_index("ix_faa_approval", "flight_approval_authorities", ["approval_id"])
    op.create_index("ix_faa_code", "flight_approval_authorities", ["authority_code"])
    op.create_index("ix_faa_status", "flight_approval_authorities", ["status"])


def downgrade() -> None:
    op.drop_index("ix_faa_status", table_name="flight_approval_authorities")
    op.drop_index("ix_faa_code", table_name="flight_approval_authorities")
    op.drop_index("ix_faa_approval", table_name="flight_approval_authorities")
    op.drop_table("flight_approval_authorities")
    op.drop_index("ix_flight_approvals_created", table_name="flight_approvals")
    op.drop_index("ix_flight_approvals_status", table_name="flight_approvals")
    op.drop_index("ix_flight_approvals_mission", table_name="flight_approvals")
    op.drop_index("ix_flight_approvals_tenant", table_name="flight_approvals")
    op.drop_table("flight_approvals")
