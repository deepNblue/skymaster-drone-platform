"""copilot v0.1 — sessions, trace_steps, approvals

Revision ID: 20260709_0002
Revises: 20260709_0001
Create Date: 2026-07-09

Adds tables per SDD v2.0-C §5:
  copilot_sessions, copilot_trace_steps, copilot_approvals
(copilot_traces already exists from initial migration.)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260709_0002"
down_revision: Union[str, None] = "20260709_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "copilot_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("total_cost_cent", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_tokens", sa.Integer(), server_default=sa.text("0")),
    )
    op.create_index("ix_copilot_sessions_org_id", "copilot_sessions", ["org_id"])
    op.create_index("ix_copilot_sessions_user_id", "copilot_sessions", ["user_id"])

    op.create_table(
        "copilot_trace_steps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(60), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column(
            "ts",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_copilot_trace_steps_trace_id", "copilot_trace_steps", ["trace_id"]
    )

    op.create_table(
        "copilot_approvals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("required_reason", sa.Text()),
        sa.Column("approver_id", postgresql.UUID(as_uuid=True)),
        sa.Column("approved_at", postgresql.TIMESTAMP(timezone=True)),
        sa.Column("decision", sa.String(20)),
        sa.Column("modifications", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("comment", sa.Text()),
    )
    op.create_index("ix_copilot_approvals_trace_id", "copilot_approvals", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_copilot_approvals_trace_id", table_name="copilot_approvals")
    op.drop_table("copilot_approvals")
    op.drop_index("ix_copilot_trace_steps_trace_id", table_name="copilot_trace_steps")
    op.drop_table("copilot_trace_steps")
    op.drop_index("ix_copilot_sessions_user_id", table_name="copilot_sessions")
    op.drop_index("ix_copilot_sessions_org_id", table_name="copilot_sessions")
    op.drop_table("copilot_sessions")
