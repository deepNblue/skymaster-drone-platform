"""Community pydantic schemas — request/response DTOs."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=20000)
    tags: list[str] | None = Field(default_factory=list)


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    author_id: UUID | None
    title: str
    body: str
    tags: list[str] | None
    moderation_status: str
    moderation_reason: str | None
    pinned: bool
    view_count: int
    like_count: int
    comment_count: int
    created_at: datetime
    updated_at: datetime


class PostList(BaseModel):
    total: int
    items: list[PostOut]


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    parent_id: UUID | None = None


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    post_id: UUID
    parent_id: UUID | None
    author_id: UUID | None
    body: str
    moderation_status: str
    like_count: int
    created_at: datetime


class ModerationDecision(BaseModel):
    action: Literal["approve", "reject", "archive"]
    reason: str | None = None
