"""copilot_tool_audit + copilot_org_tool_policy (F4.4)

Revision ID: 20260717_0041
Revises: 20260717_0040
Create Date: 2026-07-17 09:24:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260717_0041"
down_revision = "20260717_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_tool_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), index=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), index=True),
        sa.Column("tool_name", sa.String(120), nullable=False, index=True),
        sa.Column("permission", sa.String(20), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("arguments", postgresql.JSONB),
        sa.Column("result_preview", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("reason", sa.Text),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            index=True,
        ),
    )
    op.create_index(
        "ix_copilot_tool_audits_org_created",
        "copilot_tool_audits",
        ["org_id", "created_at"],
    )
    op.create_index(
        "ix_copilot_tool_audits_org_status",
        "copilot_tool_audits",
        ["org_id", "status", "created_at"],
    )

    op.create_table(
        "copilot_org_tool_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("allowlist", postgresql.JSONB),
        sa.Column("blocklist", postgresql.JSONB),
        sa.Column("max_risk_level", sa.String(20)),
        sa.Column("require_approval_above", sa.String(20)),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("copilot_org_tool_policies")
    op.drop_index(
        "ix_copilot_tool_audits_org_status",
        table_name="copilot_tool_audits",
    )
    op.drop_index(
        "ix_copilot_tool_audits_org_created",
        table_name="copilot_tool_audits",
    )
    op.drop_table("copilot_tool_audits")
