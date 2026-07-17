"""F4.1 · Copilot v2 turn feedback table.

Revision ID: 20260717_0038
Revises: 20260717_0037
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0038"
down_revision = "20260717_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_turn_feedback",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "turn_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["copilot_turns_v2.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "turn_id", "user_id", name="uq_feedback_turn_user",
        ),
        sa.CheckConstraint(
            "rating IN ('up', 'down')", name="ck_feedback_rating",
        ),
    )
    op.create_index(
        "ix_feedback_turn", "copilot_turn_feedback", ["turn_id"],
    )
    op.create_index(
        "ix_feedback_user_created", "copilot_turn_feedback",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_feedback_user_created",
        table_name="copilot_turn_feedback",
    )
    op.drop_index(
        "ix_feedback_turn", table_name="copilot_turn_feedback",
    )
    op.drop_table("copilot_turn_feedback")
