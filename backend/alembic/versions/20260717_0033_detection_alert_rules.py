"""E3.3 · Detection alert rules.

Revision ID: 20260717_0033
Revises: 20260717_0032
Create Date: 2026-07-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0033"
down_revision = "20260717_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "detection_alert_rule",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column(
            "min_member_count", sa.Integer(),
            nullable=False, server_default=sa.text("3"),
        ),
        sa.Column(
            "min_peak_confidence", sa.Float(),
            nullable=False, server_default=sa.text("0"),
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column(
            "cooldown_seconds", sa.Integer(),
            nullable=False, server_default=sa.text("300"),
        ),
        sa.Column(
            "enabled", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "last_fired_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organization.id"], ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "min_member_count >= 1",
            name="ck_alert_rule_min_member",
        ),
        sa.CheckConstraint(
            "min_peak_confidence >= 0 AND min_peak_confidence <= 1",
            name="ck_alert_rule_min_peak_conf",
        ),
        sa.CheckConstraint(
            "cooldown_seconds >= 0",
            name="ck_alert_rule_cooldown_nonneg",
        ),
        sa.CheckConstraint(
            "action IN ('log', 'feishu', 'sms')",
            name="ck_alert_rule_action",
        ),
    )
    op.create_index(
        "ix_alert_rule_org_enabled",
        "detection_alert_rule",
        ["org_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_alert_rule_org_enabled", table_name="detection_alert_rule",
    )
    op.drop_table("detection_alert_rule")
