"""copilot_task_chain tables (v2.1 E2.4)

Revision ID: 20260717_0045
Revises: 20260717_0044
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260717_0045"
down_revision = "20260717_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_task_chains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), index=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("plan_json", postgresql.JSONB),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("current_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reflection_notes", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index(
        "ix_copilot_task_chains_org_status",
        "copilot_task_chains", ["org_id", "status"],
    )

    op.create_table(
        "copilot_task_chain_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("step_index", sa.Integer, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("tool", sa.String(128), nullable=False),
        sa.Column("args_planned", postgresql.JSONB),
        sa.Column("args_resolved", postgresql.JSONB),
        sa.Column("output_json", postgresql.JSONB),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
    )

    op.create_table(
        "copilot_task_chain_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chain_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("at_step_index", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("prev_plan", postgresql.JSONB),
        sa.Column("new_plan", postgresql.JSONB),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("copilot_task_chain_revisions")
    op.drop_table("copilot_task_chain_steps")
    op.drop_index(
        "ix_copilot_task_chains_org_status", table_name="copilot_task_chains",
    )
    op.drop_table("copilot_task_chains")
