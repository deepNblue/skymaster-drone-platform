"""3DGS Scene tables — v2.1 T1."""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260713_0019"
down_revision: Union[str, None] = "20260710_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scenes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organization.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("missions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column("coord_system", sa.String(40), nullable=True),
        sa.Column("n_source_images", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_points", sa.Integer, nullable=True),
        sa.Column("n_gaussians", sa.Integer, nullable=True),
        sa.Column("psnr_train", sa.Float, nullable=True),
        sa.Column("metadata", postgresql.JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_scenes_org_id", "scenes", ["org_id"])
    op.create_index("ix_scenes_owner_user_id", "scenes", ["owner_user_id"])
    op.create_index("ix_scenes_mission_id", "scenes", ["mission_id"])
    op.create_index("ix_scenes_status", "scenes", ["status"])

    op.create_table(
        "scene_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("scene_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("sha256_hex", sa.String(64), nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("ix_scene_assets_scene_id", "scene_assets", ["scene_id"])
    op.create_index("ix_scene_assets_kind", "scene_assets", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_scene_assets_kind", table_name="scene_assets")
    op.drop_index("ix_scene_assets_scene_id", table_name="scene_assets")
    op.drop_table("scene_assets")
    op.drop_index("ix_scenes_status", table_name="scenes")
    op.drop_index("ix_scenes_mission_id", table_name="scenes")
    op.drop_index("ix_scenes_owner_user_id", table_name="scenes")
    op.drop_index("ix_scenes_org_id", table_name="scenes")
    op.drop_table("scenes")
