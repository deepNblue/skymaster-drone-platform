"""Pydantic schemas for drone endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


DroneProtocol = Literal["mavlink", "dji", "custom"]
DroneStatus = Literal["online", "offline", "flying", "error"]


class DroneCreate(BaseModel):
    sn: str = Field(..., min_length=1, max_length=60)
    model: str | None = Field(default=None, max_length=60)
    protocol: DroneProtocol
    metadata: dict[str, Any] = Field(default_factory=dict)


class DroneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID | None = None
    sn: str
    model: str | None = None
    protocol: str
    status: str | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="metadata")
    created_at: datetime | None = None


class DroneListParams(BaseModel):
    status: str | None = None
    protocol: str | None = None
    q: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
