"""v2.0 R12 — Users: failed_login_count, locked_until, totp_secret, totp_enabled.

Revision ID: 20260710_0006
Revises: 20260710_0005
Create Date: 2026-07-10 04:32:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0006"
down_revision: Union[str, None] = "20260710_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_login_count", sa.Integer(),
            server_default="0", nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "locked_until", sa.DateTime(timezone=True), nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("totp_secret", sa.String(64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "totp_enabled", sa.Boolean(),
            server_default=sa.text("false"), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
