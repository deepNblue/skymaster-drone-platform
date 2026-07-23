"""F3.4 · Community notifications table.

Revision ID: 20260717_0037
Revises: 20260717_0036
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0037"
down_revision = "20260717_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_notifications",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "recipient_id", postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "post_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column(
            "comment_id", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column(
            "read_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "kind IN ('new_follower', 'post_liked', "
            "'post_reply', 'mention')",
            name="ck_notification_kind",
        ),
    )
    op.create_index(
        "ix_notif_recipient_created",
        "community_notifications",
        ["recipient_id", "created_at"],
    )
    op.create_index(
        "ix_notif_recipient_unread",
        "community_notifications",
        ["recipient_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notif_recipient_unread",
        table_name="community_notifications",
    )
    op.drop_index(
        "ix_notif_recipient_created",
        table_name="community_notifications",
    )
    op.drop_table("community_notifications")
