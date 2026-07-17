"""audit_logs.sig_hex + sig_key_id — R21 Step F.

Adds SM2 signature columns to the append-only audit log for non-repudiation.
Existing rows stay NULL; only rows written after this migration + with
SM2_PRIVATE_KEY_HEX configured will have signatures.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0016"
down_revision: Union[str, None] = "20260710_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("sig_hex", sa.String(160), nullable=True))
    op.add_column("audit_logs", sa.Column("sig_key_id", sa.String(32), nullable=True))
    op.create_index("ix_audit_logs_sig_key_id", "audit_logs", ["sig_key_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_sig_key_id", table_name="audit_logs")
    op.drop_column("audit_logs", "sig_key_id")
    op.drop_column("audit_logs", "sig_hex")
