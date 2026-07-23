"""D3.1 · 4DGS scene frames — per-frame temporal metadata.

Revision ID: 20260717_0032
Revises: 20260717_0031
Create Date: 2026-07-17

Rationale
=========
``scenes.scene_kind = '4dgs'`` scenes have ``n_frames`` in aggregate,
but currently no per-frame metadata. Reality Studio's time slider
needs:

* ``frame_index`` (0..N-1) for O(1) lookup
* ``captured_at`` absolute timestamp so labels can display real times
* ``is_keyframe`` bool — timeline snap-points for scrubbing
* ``psnr_frame`` per-frame reconstruction quality
* ``lighting`` free-form tag (day / dusk / night / overcast) for
  weather-aware analytics
* ``notes`` for operators to jot down "this frame is the incident
  moment" style annotations

Schema
------
Composite unique (scene_id, frame_index) — enforces one row per frame
per scene. FK ondelete=CASCADE — dropping a scene drops its frames.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260717_0032"
down_revision = "20260717_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scene_frame",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scene_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column(
            "captured_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "is_keyframe", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("psnr_frame", sa.Float(), nullable=True),
        sa.Column(
            "lighting", sa.String(24), nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["scene_id"], ["scenes.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "scene_id", "frame_index", name="uq_scene_frame_scene_idx",
        ),
        sa.CheckConstraint(
            "frame_index >= 0", name="ck_scene_frame_nonneg",
        ),
    )
    op.create_index(
        "ix_scene_frame_scene_ts",
        "scene_frame",
        ["scene_id", "captured_at"],
    )
    op.create_index(
        "ix_scene_frame_scene_keyframe",
        "scene_frame",
        ["scene_id", "is_keyframe"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scene_frame_scene_keyframe", table_name="scene_frame",
    )
    op.drop_index(
        "ix_scene_frame_scene_ts", table_name="scene_frame",
    )
    op.drop_table("scene_frame")
