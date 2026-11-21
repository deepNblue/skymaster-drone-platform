"""v2.0 §3.18 Community MVP — posts + comments with moderation.

Revision ID: 20260713_0020
Revises: 20260713_0019
Create Date: 2026-07-13 15:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260713_0020"
down_revision: Union[str, None] = "20260713_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "community_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("author_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column("moderation_status", sa.String(16), nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column("moderation_reason", sa.String(512), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("view_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("like_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("comment_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_community_posts_tenant_id", "community_posts", ["tenant_id"])
    op.create_index("ix_community_posts_moderation_status",
                    "community_posts", ["moderation_status"])
    op.create_index("ix_community_posts_created_at", "community_posts", ["created_at"])

    op.create_table(
        "community_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("post_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("community_posts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("community_comments.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("author_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("moderation_status", sa.String(16), nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column("moderation_reason", sa.String(512), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_community_comments_post_id", "community_comments", ["post_id"])
    op.create_index("ix_community_comments_parent_id",
                    "community_comments", ["parent_id"])
    op.create_index("ix_community_comments_moderation_status",
                    "community_comments", ["moderation_status"])
    op.create_index("ix_community_comments_created_at",
                    "community_comments", ["created_at"])


def downgrade() -> None:
    op.drop_table("community_comments")
    op.drop_table("community_posts")
