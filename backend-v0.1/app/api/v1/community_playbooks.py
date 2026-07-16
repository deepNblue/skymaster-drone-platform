"""T11.2 · Community playbook REST API.

Endpoints
=========
POST   /community-playbooks              submit a new playbook (pending)
GET    /community-playbooks              list approved (+ own pending)
GET    /community-playbooks/{slug}       fetch one
DELETE /community-playbooks/{slug}       soft-delete (author or admin)
POST   /community-playbooks/{slug}/moderate    approve/reject (admin only)
POST   /community-playbooks/{slug}/install     fork into caller's org
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.community_playbooks import (
    PlaybookError,
    delete_playbook,
    fork_to_workflow,
    get_playbook,
    list_playbooks,
    moderate_playbook,
    submit_playbook,
)

router = APIRouter(
    prefix="/community-playbooks",
    tags=["community-playbooks"],
)


# ============================================================ Schemas ==


class PlaybookOut(BaseModel):
    slug: str
    name: str
    description: str
    dsl_yaml: str
    sample_inputs: dict[str, Any]
    tags: list[str]
    status: str
    rejected_reason: str | None
    install_count: int
    author_user_id: UUID
    org_id: UUID
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

    @classmethod
    def from_row(cls, r) -> "PlaybookOut":
        return cls(
            slug=r.slug,
            name=r.name,
            description=r.description or "",
            dsl_yaml=r.dsl_yaml,
            sample_inputs=r.sample_inputs_json or {},
            tags=list(r.tags or []),
            status=r.status,
            rejected_reason=r.rejected_reason,
            install_count=r.install_count or 0,
            author_user_id=r.author_user_id,
            org_id=r.org_id,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )


class SubmitPayload(BaseModel):
    slug: str = Field(..., min_length=2, max_length=60)
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    dsl_yaml: str = Field(..., min_length=1)
    sample_inputs: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=8)


class ModeratePayload(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=500)


class InstallResponse(BaseModel):
    workflow_id: UUID
    workflow_name: str


# ============================================================= Endpoints


def _map_error(exc: PlaybookError) -> HTTPException:
    msg = str(exc)
    lower = msg.lower()
    if "not found" in lower:
        return HTTPException(404, msg)
    if "only" in lower or "cannot fork" in lower:
        return HTTPException(403, msg)
    return HTTPException(400, msg)


@router.post("", response_model=PlaybookOut, status_code=201)
async def api_submit(
    payload: SubmitPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlaybookOut:
    try:
        row = await submit_playbook(
            db,
            org_id=user.org_id,
            author_user_id=user.id,
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            dsl_yaml=payload.dsl_yaml,
            sample_inputs=payload.sample_inputs,
            tags=payload.tags,
        )
    except PlaybookError as exc:
        raise _map_error(exc)
    return PlaybookOut.from_row(row)


@router.get("", response_model=list[PlaybookOut])
async def api_list(
    status: str | None = None,
    include_own: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PlaybookOut]:
    try:
        rows = await list_playbooks(
            db,
            org_id=user.org_id,
            status=status,
            include_own_pending=include_own,
            limit=min(max(limit, 1), 200),
        )
    except PlaybookError as exc:
        raise _map_error(exc)
    return [PlaybookOut.from_row(r) for r in rows]


@router.get("/{slug}", response_model=PlaybookOut)
async def api_get(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlaybookOut:
    row = await get_playbook(db, slug=slug)
    if row is None:
        raise HTTPException(404, "playbook not found")
    # Non-approved is visible only to the author's org.
    if row.status != "approved" and row.org_id != user.org_id:
        raise HTTPException(404, "playbook not found")
    return PlaybookOut.from_row(row)


@router.delete("/{slug}", status_code=204)
async def api_delete(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        ok = await delete_playbook(
            db,
            slug=slug,
            requester_org_id=user.org_id,
            requester_user_id=user.id,
            is_admin=(user.role == "admin"),
        )
    except PlaybookError as exc:
        raise _map_error(exc)
    if not ok:
        raise HTTPException(404, "playbook not found")


@router.post("/{slug}/moderate", response_model=PlaybookOut)
async def api_moderate(
    slug: str,
    payload: ModeratePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlaybookOut:
    if user.role != "admin":
        raise HTTPException(403, "moderator role required")
    try:
        row = await moderate_playbook(
            db,
            slug=slug,
            reviewer_id=user.id,
            approve=payload.approve,
            reason=payload.reason,
        )
    except PlaybookError as exc:
        raise _map_error(exc)
    return PlaybookOut.from_row(row)


@router.post("/{slug}/install", response_model=InstallResponse)
async def api_install(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InstallResponse:
    try:
        wf = await fork_to_workflow(
            db,
            slug=slug,
            target_org_id=user.org_id,
            target_user_id=user.id,
        )
    except PlaybookError as exc:
        raise _map_error(exc)
    return InstallResponse(workflow_id=wf.id, workflow_name=wf.name)
