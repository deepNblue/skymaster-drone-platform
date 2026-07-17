"""video_streams + video_stream_probes — R21 Step H."""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0017"
down_revision: Union[str, None] = "20260710_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_streams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "drone_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drones.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("protocol", sa.String(16), nullable=False),
        sa.Column("source_url", sa.String(1024), nullable=False),
        sa.Column("play_url", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="idle"),
        sa.Column("bitrate_kbps", sa.Integer, nullable=True),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column("fps", sa.Integer, nullable=True),
        sa.Column("codec", sa.String(32), nullable=True),
        sa.Column("meta", postgresql.JSONB, nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_video_streams_drone_id", "video_streams", ["drone_id"])
    op.create_index("ix_video_streams_status", "video_streams", ["status"])
    op.create_index("ix_video_streams_protocol", "video_streams", ["protocol"])

    op.create_table(
        "video_stream_probes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "stream_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_streams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("probe_status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_video_stream_probes_stream_id", "video_stream_probes", ["stream_id"],
    )


def downgrade() -> None:
    op.drop_table("video_stream_probes")
    op.drop_table("video_streams")
