"""widen approval status columns to String(24)

'pending_second_approval' (22 chars) overflowed varchar(16):
- SQLite silently accepts (no length enforcement) - bug stayed hidden
- PostgreSQL raises 'value too long' - blocked special-category E2E

Bump flight_approvals.status and flight_approval_authorities.status
to varchar(24) on both dialects (batch mode rebuilds the table on
SQLite, plain ALTER on PG).

Revision ID: 20260815_0048
Revises: 20260721_0047_add_v23_tables
Create Date: 2026-08-15 05:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = '20260815_0048'
down_revision = '20260721_0047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('flight_approvals') as batch:
        batch.alter_column(
            'status',
            existing_type=sa.String(length=16),
            type_=sa.String(length=24),
            existing_nullable=False,
        )
    with op.batch_alter_table('flight_approval_authorities') as batch:
        batch.alter_column(
            'status',
            existing_type=sa.String(length=16),
            type_=sa.String(length=24),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('flight_approvals') as batch:
        batch.alter_column(
            'status',
            existing_type=sa.String(length=24),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
    with op.batch_alter_table('flight_approval_authorities') as batch:
        batch.alter_column(
            'status',
            existing_type=sa.String(length=24),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
