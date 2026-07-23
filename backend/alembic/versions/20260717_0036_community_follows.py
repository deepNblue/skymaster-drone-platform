"""F3.3 · Community follow relationships.

Revision ID: 20260717_0036
Revises: 20260717_0034
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0036"
down_revision = "20260717_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_follows",
        sa.Column(
            "follower_id", postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "followed_id", postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("follower_id", "followed_id"),
        sa.ForeignKeyConstraint(
            ["follower_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["followed_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "follower_id <> followed_id",
            name="ck_follow_no_self",
        ),
    )
    op.create_index(
        "ix_follow_follower_created",
        "community_follows",
        ["follower_id", "created_at"],
    )
    op.create_index(
        "ix_follow_followed_created",
        "community_follows",
        ["followed_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_follow_followed_created", table_name="community_follows",
    )
    op.drop_index(
        "ix_follow_follower_created", table_name="community_follows",
    )
    op.drop_table("community_follows")
