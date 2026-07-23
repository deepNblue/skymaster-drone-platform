"""CopilotWorkflow Marketplace 数据模型 (v2.1 E2.6).

将用户创建的 workflow 发布到市场，供其他用户浏览、克隆、评分。

三张表:
- CopilotWorkflowListing: 一个 published listing（workflow 的一次快照）
- CopilotWorkflowRating: 用户对某 listing 的评分/评论
- CopilotWorkflowInstall: 克隆记录（谁 clone 了哪个 listing）
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CopilotWorkflowListing(Base):
    """已发布到市场的 workflow 快照.

    发布时冻结 ``dsl_yaml`` 的当前值——市场里的每个 listing 是不可变快照。
    源 workflow 后续版本更新不会自动传播；作者需要重新发布。
    """

    __tablename__ = "copilot_workflow_listings"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    author_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(
        String(2048), nullable=False, default="",
        server_default=text("''"),
    )
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    dsl_yaml_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="public",
        server_default=text("'public'"),
    )  # public | org | private
    install_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    avg_rating: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0"),
    )
    rating_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    published_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    unpublished_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True)
    )

    __table_args__ = (
        Index(
            "ix_copilot_workflow_listings_visibility_alive",
            "visibility",
            sqlite_where=text("unpublished_at IS NULL"),
            postgresql_where=text("unpublished_at IS NULL"),
        ),
    )


class CopilotWorkflowRating(Base):
    """用户对某 listing 的评分 (1-5 星) + 可选评论."""

    __tablename__ = "copilot_workflow_ratings"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    listing_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    rater_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False
    )
    rater_org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    stars: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..5
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint("listing_id", "rater_user_id", name="uq_wl_rating_once"),
    )


class CopilotWorkflowInstall(Base):
    """一次克隆记录：谁把哪个 listing 装到自己的 workspace."""

    __tablename__ = "copilot_workflow_installs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    listing_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    installer_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False
    )
    installer_org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    new_workflow_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False
    )
    installed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
