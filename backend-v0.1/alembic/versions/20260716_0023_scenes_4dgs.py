"""T9.11 (v2.1 D2.1) — 4DGS temporal support on scenes.

Adds three columns to ``scenes`` for the Reality Studio v2.1 upgrade:

* ``scene_kind``   (str, NOT NULL, default '3dgs'):
  Enum-like tag ∈ {'3dgs', '4dgs'}. Existing rows default to '3dgs'
  so behaviour is unchanged. New 4DGS jobs set this to '4dgs' at
  ingest time.
* ``n_frames``     (int, nullable):
  Number of temporal frames the 4DGS reconstruction consumed. NULL
  for '3dgs' scenes.
* ``psnr_temporal`` (float, nullable):
  PSNR evaluated on held-out temporal frames. Companion to the
  existing ``psnr_train`` metric which stays as spatial-only.

Rollback (downgrade) is straightforward: drops the three columns.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers.
revision = "20260716_0023"
down_revision = "20260714_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scenes",
        sa.Column(
            "scene_kind",
            sa.String(length=10),
            server_default=sa.text("'3dgs'"),
            nullable=False,
        ),
    )
    op.add_column("scenes", sa.Column("n_frames", sa.Integer(), nullable=True))
    op.add_column(
        "scenes", sa.Column("psnr_temporal", sa.Float(), nullable=True)
    )
    op.create_index(
        "ix_scenes_scene_kind", "scenes", ["scene_kind"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_scenes_scene_kind", table_name="scenes")
    op.drop_column("scenes", "psnr_temporal")
    op.drop_column("scenes", "n_frames")
    op.drop_column("scenes", "scene_kind")
