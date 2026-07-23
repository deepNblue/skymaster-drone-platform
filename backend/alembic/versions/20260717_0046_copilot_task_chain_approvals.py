"""copilot_task_chain_approvals (v2.1 E2.5)

Revision ID: 20260717_0046
Revises: 20260717_0045
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260717_0046"
down_revision = "20260717_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_task_chain_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("step_index", sa.Integer, nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("permission", sa.String(16), nullable=False),
        sa.Column("required_reason", sa.Text, nullable=False),
        sa.Column("args_snapshot", postgresql.JSONB),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("approver_id", postgresql.UUID(as_uuid=True)),
        sa.Column("decision_reason", sa.Text),
        sa.Column("modifications", postgresql.JSONB),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("copilot_task_chain_approvals")
