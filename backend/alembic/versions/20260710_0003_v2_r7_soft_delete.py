"""v2.0 R7 — add User.is_active + audit_logs.actor_role.

Adds soft-delete flag for users (admin CRUD deactivate flow) and captures
the role of every audited action for downstream compliance analytics.

Revision ID: 20260710_0003
Revises: 20260709_0002
Create Date: 2026-07-10 03:10:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260710_0003"
down_revision: Union[str, None] = "20260709_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users.is_active ---
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_index("ix_users_is_active", "users", ["is_active"])

    # --- audit_logs.actor_role ---
    op.add_column(
        "audit_logs",
        sa.Column("actor_role", sa.String(length=30), nullable=True),
    )
    op.create_index("ix_audit_logs_actor_role", "audit_logs", ["actor_role"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_actor_role", table_name="audit_logs")
    op.drop_column("audit_logs", "actor_role")
    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_column("users", "is_active")
