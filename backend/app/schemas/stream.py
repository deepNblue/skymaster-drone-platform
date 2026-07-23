"""Pydantic schemas for video stream endpoints."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class StreamRegisterRequest(BaseModel):
    """Register a new mediamtx path fed from a drone video downlink."""

    source_url: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="RTSP/RTMP source URL from the drone video downlink",
    )


class StreamOut(BaseModel):
    """Public representation of a registered mediamtx stream."""

    drone_id: UUID
    name: str
    hls_url: str
    rtsp_url: str
    active: bool
    source_url: str | None = None


__all__ = ["StreamRegisterRequest", "StreamOut"]
