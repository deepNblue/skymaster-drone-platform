"""Pydantic schemas for mission endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


MissionTemplate = Literal["waypoint", "grid", "orbit"]
MissionStatus = Literal["draft", "dispatched", "running", "done", "failed"]


class WaypointSchema(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)
    alt: float = Field(..., description="Altitude in meters (AGL)")
    speed: float | None = Field(default=None, ge=0.0)
    action: str | None = None


class MissionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    drone_id: UUID | None = None
    template: MissionTemplate | None = None
    waypoints: list[WaypointSchema] = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class MissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID | None = None
    drone_id: UUID | None = None
    name: str
    template: str | None = None
    waypoints: list[dict[str, Any]]
    params: dict[str, Any] | None = None
    status: str | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None
