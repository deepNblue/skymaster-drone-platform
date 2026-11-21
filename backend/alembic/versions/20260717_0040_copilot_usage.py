"""F4.3 · Copilot usage & org quota.

Revision ID: 20260717_0040
Revises: 20260717_0039
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0040"
down_revision = "20260717_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_usage",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True)),
        sa.Column("persona", sa.String(24)),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column(
            "prompt_tokens", sa.Integer,
            nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "completion_tokens", sa.Integer,
            nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "latency_ms", sa.Integer,
            nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_units", sa.Numeric(12, 4),
            nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default=sa.text("'ok'"),
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0",
            name="ck_usage_tokens_nonneg",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0", name="ck_usage_latency_nonneg",
        ),
        sa.CheckConstraint(
            "cost_units >= 0", name="ck_usage_cost_nonneg",
        ),
    )
    op.create_index(
        "ix_usage_org_created", "copilot_usage",
        ["org_id", "created_at"],
    )
    op.create_index(
        "ix_usage_persona_created", "copilot_usage",
        ["persona", "created_at"],
    )
    op.create_index(
        "ix_usage_status_created", "copilot_usage",
        ["status", "created_at"],
    )

    op.create_table(
        "copilot_org_quota",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "monthly_token_budget", sa.Integer,
            nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "hard_stop", sa.Boolean,
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", name="uq_org_quota"),
        sa.CheckConstraint(
            "monthly_token_budget >= 0",
            name="ck_quota_budget_nonneg",
        ),
    )


def downgrade() -> None:
    op.drop_table("copilot_org_quota")
    op.drop_index(
        "ix_usage_status_created", table_name="copilot_usage",
    )
    op.drop_index(
        "ix_usage_persona_created", table_name="copilot_usage",
    )
    op.drop_index(
        "ix_usage_org_created", table_name="copilot_usage",
    )
    op.drop_table("copilot_usage")
