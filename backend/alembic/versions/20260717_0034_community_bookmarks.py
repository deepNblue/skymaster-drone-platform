"""F3.1 · Community post bookmarks.

Revision ID: 20260717_0034
Revises: 20260717_0033
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0034"
down_revision = "20260717_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_bookmarks",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "post_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("user_id", "post_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["community_posts.id"], ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_bookmark_user_created",
        "community_bookmarks",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bookmark_user_created", table_name="community_bookmarks",
    )
    op.drop_table("community_bookmarks")
