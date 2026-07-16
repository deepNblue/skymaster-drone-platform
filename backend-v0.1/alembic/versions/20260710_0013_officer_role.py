"""v2.0 R19 — three-officer separation of duty column.

Revision ID: 20260710_0013
Revises: 20260710_0012
Create Date: 2026-07-10 11:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0013"
down_revision: Union[str, None] = "20260710_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("officer_role", sa.String(24), nullable=True))
    op.create_index("ix_users_officer_role", "users", ["officer_role"])


def downgrade() -> None:
    op.drop_index("ix_users_officer_role", table_name="users")
    op.drop_column("users", "officer_role")
