"""Model Marketplace pydantic schemas — request/response DTOs."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------
class ListingCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9\-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    task: str = Field(..., max_length=32)
    framework: str = Field(..., max_length=32)
    tags: list[str] | None = None
    visibility: Literal["public", "private", "org"] = "public"
    license: str = Field(default="proprietary", max_length=32)
    price_model: Literal["free", "per_call", "per_frame", "per_token", "per_month"] = "free"
    price_unit: Decimal | None = None
    currency: str = Field(default="CNY", max_length=8)


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    description: str | None
    task: str
    framework: str
    tags: list[str] | None
    visibility: str
    owner_org_id: UUID | None
    owner_user_id: UUID | None
    license: str
    price_model: str
    price_unit: Decimal | None
    currency: str
    is_featured: bool
    created_at: datetime
    updated_at: datetime


class ListingPage(BaseModel):
    total: int
    items: list[ListingOut]


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
class VersionCreate(BaseModel):
    version: str = Field(..., max_length=32)
    artifact_uri: str = Field(..., max_length=1024)
    artifact_sha256: str = Field(..., min_length=64, max_length=64)
    size_bytes: int | None = None
    inputs_schema: dict | None = None
    outputs_schema: dict | None = None
    hardware: list[str] | None = None
    benchmark: dict | None = None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    listing_id: UUID
    version: str
    artifact_uri: str
    artifact_sha256: str
    size_bytes: int | None
    inputs_schema: dict | None
    outputs_schema: dict | None
    hardware: list[str] | None
    benchmark: dict | None
    review_status: str
    review_note: str | None
    reviewer_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime


class VersionReview(BaseModel):
    action: Literal["approve", "reject", "withdraw"]
    note: str | None = None


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------
class DeploymentCreate(BaseModel):
    endpoint_url: str | None = None
    quota_calls_per_day: int | None = None


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    listing_id: UUID
    version_id: UUID
    status: str
    endpoint_url: str | None
    quota_calls_per_day: int | None
    installed_by: UUID | None
    installed_at: datetime
    updated_at: datetime


class UsageRecord(BaseModel):
    units: int = Field(..., ge=1)
    unit_type: Literal["call", "frame", "token"] = "call"
    latency_ms: float | None = None
    outcome: str = "ok"
    meta: dict | None = None


class UsageSummary(BaseModel):
    deployment_id: UUID
    since_days: int
    total_units: int
    by_outcome: dict[str, int]
