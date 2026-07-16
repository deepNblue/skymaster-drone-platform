"""Scene ORM model — v2.1 T1 (3DGS Reality Studio).

A **Scene** is the top-level unit of the 3D reconstruction pipeline:

    upload images/video  →  COLMAP structure-from-motion  →  Gaussian Splatting training
                                                                       │
                                                                       ▼
                                                          exportable .ply / .splat asset

We model this as a two-table schema:

* ``scenes``       — one row per reconstruction target, holds state machine
                     status + coordinate system + owner + summary metrics.
* ``scene_assets`` — one row per uploaded/generated file (source photos,
                     COLMAP outputs, trained ``.ply``, previews).

Scene status is a hard state machine (transitions in
``services/scene_pipeline.py``). Never mutate the column directly outside
the pipeline service.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# ---------------------------------------------------------------------------
# Status values (hard-coded enum for portability across dialects)
# ---------------------------------------------------------------------------

# Life cycle for a scene from creation to a usable 3DGS model.
SCENE_STATUSES: tuple[str, ...] = (
    "draft",         # created, no assets yet
    "ingesting",     # assets are uploading
    "ingested",      # all source assets present, ready for COLMAP
    "colmap",        # SfM running
    "colmap_done",   # sparse point cloud + camera poses ready
    "training",      # Gaussian splatting training running
    "ready",         # trained .ply/.splat available, downloadable
    "failed",        # any stage errored (see error_msg)
    "archived",      # user retired the scene; assets kept read-only
)

# Kinds of files a scene may hold.
SCENE_ASSET_KINDS: tuple[str, ...] = (
    "source_image",
    "source_video",
    "colmap_sparse",
    "colmap_dense",
    "gsplat_ckpt",
    "gsplat_ply",
    "preview_thumb",
    "log",
)


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="SET NULL"),
        index=True,
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    # Optional linkage — if the scene was reconstructed from a specific mission
    mission_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="SET NULL"),
        index=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Hard state machine — enforced in the pipeline service.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft", index=True
    )
    error_msg: Mapped[str | None] = mapped_column(Text)

    # WGS84 / local ENU / relative — free-form so we don't lock a taxonomy
    coord_system: Mapped[str | None] = mapped_column(String(40))

    # Summary metrics filled in when training completes.
    n_source_images: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    n_points: Mapped[int | None] = mapped_column(Integer)
    n_gaussians: Mapped[int | None] = mapped_column(Integer)
    psnr_train: Mapped[float | None] = mapped_column(Float)

    meta: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )

    assets: Mapped[list["SceneAsset"]] = relationship(
        "SceneAsset", back_populates="scene", cascade="all, delete-orphan"
    )


class SceneAsset(Base):
    __tablename__ = "scene_assets"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    scene_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256_hex: Mapped[str | None] = mapped_column(String(64))
    uploaded_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )

    scene: Mapped[Scene] = relationship("Scene", back_populates="assets")
