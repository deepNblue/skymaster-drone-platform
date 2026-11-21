"""v2.0 R18 — audit log tamper-evident columns.

Revision ID: 20260710_0012
Revises: 20260710_0011
Create Date: 2026-07-10 10:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0012"
down_revision: Union[str, None] = "20260710_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("curr_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("diff_ct", sa.Text(), nullable=True))
    op.create_index("ix_audit_logs_curr_hash", "audit_logs", ["curr_hash"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_curr_hash", table_name="audit_logs")
    op.drop_column("audit_logs", "diff_ct")
    op.drop_column("audit_logs", "curr_hash")
    op.drop_column("audit_logs", "prev_hash")
