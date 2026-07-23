"""Scene Marketplace ORM models — v2.1 T2.0.

Marketplace = cross-org catalog of published 3DGS scenes. Any org can:

  * **publish** their own scenes as ``SceneListing`` rows with title,
    description, license, cover thumb, tags
  * **browse** other orgs' public listings (paginated + filterable)
  * **clone** a listing back into their own workspace as a new ``Scene``
    (metadata-only clone; the raw ``.ply`` stays in the seller's CAS)
  * **review** listings with a 0–5 star rating + optional comment

Non-goals for this table set
----------------------------
* Payment / billing gateway → v2.2
* Access-controlled paid downloads → v2.3
* Featured / editor's picks curation → v2.1 T2.1

Design principle: **published scene = immutable snapshot**. If the source
scene is retrained, the listing does not automatically update — we require
a fresh ``publish`` (which creates a new listing pointing at the newer
scene). This gives buyers a stable provenance trail.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


SCENE_LISTING_VISIBILITIES: tuple[str, ...] = ("public", "org_only", "unlisted")
SCENE_LISTING_STATUSES: tuple[str, ...] = ("active", "archived", "removed")
SCENE_LISTING_LICENSES: tuple[str, ...] = (
    "CC0", "CC-BY", "CC-BY-SA", "CC-BY-NC", "CC-BY-NC-SA", "proprietary",
)

# v2.1 T2.1 · discovery categories. Kept small on purpose — a bigger
# taxonomy invites bikeshedding; we can always extend later.
SCENE_LISTING_CATEGORIES: tuple[str, ...] = (
    "tourism",       # 旅游景区、地标
    "engineering",   # 工程、桥梁、施工现场
    "emergency",     # 应急、灾害、救援
    "agriculture",   # 农业、林业
    "urban",         # 城市街区、园区
    "industrial",    # 工业厂房、变电站
    "other",
)


class SceneListing(Base):
    """A publicly-visible catalog entry for a shared 3DGS scene."""

    __tablename__ = "scene_listings"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_scene_listings_slug"),
        CheckConstraint(
            "visibility IN ('public','org_only','unlisted')",
            name="ck_scene_listings_visibility",
        ),
        CheckConstraint(
            "status IN ('active','archived','removed')",
            name="ck_scene_listings_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    scene_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    publisher_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    slug: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    cover_asset_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )  # references scene_assets.id but not FK-constrained (soft-link)

    visibility: Mapped[str] = mapped_column(String(16), nullable=False, server_default="public", index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active", index=True)
    license: Mapped[str] = mapped_column(String(32), nullable=False, server_default="CC-BY-NC")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # v2.1 T2.1 · discovery signals
    category: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    is_featured: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false", index=True)
    featured_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    featured_note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # snapshotted metrics at publish time (immutable)
    n_gaussians: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scene_extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    clone_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    reviews: Mapped[list["SceneListingReview"]] = relationship(
        "SceneListingReview", back_populates="listing", cascade="all, delete-orphan",
    )
    clones: Mapped[list["SceneListingClone"]] = relationship(
        "SceneListingClone", back_populates="listing", cascade="all, delete-orphan",
    )


class SceneListingReview(Base):
    __tablename__ = "scene_listing_reviews"
    __table_args__ = (
        UniqueConstraint("listing_id", "user_id", name="uq_scene_listing_review_per_user"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_scene_listing_review_rating"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scene_listings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
    )

    listing: Mapped[SceneListing] = relationship("SceneListing", back_populates="reviews")


class SceneListingClone(Base):
    """Provenance record — one row per clone from a listing to a scene."""

    __tablename__ = "scene_listing_clones"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scene_listings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    cloned_scene_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    cloned_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cloned_by_org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(),
    )

    listing: Mapped[SceneListing] = relationship("SceneListing", back_populates="clones")
