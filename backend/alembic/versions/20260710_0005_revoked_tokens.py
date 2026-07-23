"""v2.0 R11 — RevokedToken table for JWT jti blacklist.

Revision ID: 20260710_0005
Revises: 20260710_0004
Create Date: 2026-07-10 04:08:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260710_0005"
down_revision: Union[str, None] = "20260710_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        sa.Column("exp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("reason", sa.String(64), nullable=True),
    )
    op.create_index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"])
    op.create_index("ix_revoked_tokens_exp", "revoked_tokens", ["exp"])


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_exp", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
