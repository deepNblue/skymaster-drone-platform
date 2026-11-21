"""API: /copilot/memory — 长期记忆 CRUD + 检索 (v2.1 E2.3)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services import copilot_memory as svc

router = APIRouter(prefix="/copilot/memory", tags=["copilot-memory"])

_KINDS = ("preference", "fact", "task_history", "insight")


class MemoryIn(BaseModel):
    kind: str = Field(..., description="preference|fact|task_history|insight")
    content: str = Field(..., min_length=1, max_length=4000)
    scope: str = Field(default="user", description="user|org")
    key: str | None = None
    tags: list[str] | None = None
    meta: dict[str, Any] | None = None
    ttl_days: int | None = Field(default=None, ge=0, le=3650)
    weight: int = Field(default=50, ge=0, le=100)


class MemoryOut(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID | None = None
    kind: str
    scope: str
    key: str | None = None
    content: str
    tags: list[str] | None = None
    meta: dict[str, Any] | None = None
    ttl_days: int | None = None
    weight: int
    hit_count: int
    created_at: datetime | None = None
    last_hit_at: datetime | None = None
    source_trace_id: UUID | None = None


class MemoryHit(BaseModel):
    memory: MemoryOut
    score: float
    reason: str


@router.post("", response_model=MemoryOut)
async def api_create(
    body: MemoryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemoryOut:
    if body.kind not in _KINDS:
        raise HTTPException(400, f"invalid kind: {body.kind}")
    if body.scope not in ("user", "org"):
        raise HTTPException(400, f"invalid scope: {body.scope}")
    mem = await svc.create_memory(
        db,
        org_id=user.org_id,
        user_id=(user.id if body.scope == "user" else None),
        kind=body.kind, content=body.content, scope=body.scope,
        key=body.key, tags=body.tags, meta=body.meta,
        ttl_days=body.ttl_days, weight=body.weight,
    )
    return MemoryOut.model_validate(mem, from_attributes=True)


@router.get("/search", response_model=list[MemoryHit])
async def api_search(
    q: str = Query(default=""),
    kind: list[str] | None = Query(default=None),
    tag: list[str] | None = Query(default=None),
    top_k: int = Query(default=5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MemoryHit]:
    if kind:
        for k in kind:
            if k not in _KINDS:
                raise HTTPException(400, f"invalid kind: {k}")
    hits = await svc.search_memory(
        db,
        org_id=user.org_id, user_id=user.id,
        query=q, kinds=kind, tags=tag, top_k=top_k,
    )
    # Bump hit counters
    if hits:
        await svc.touch(db, memory_ids=[h.memory.id for h in hits])
    return [
        MemoryHit(
            memory=MemoryOut.model_validate(h.memory, from_attributes=True),
            score=h.score, reason=h.reason,
        )
        for h in hits
    ]


@router.get("/stats", response_model=dict[str, int])
async def api_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    return await svc.memory_stats(db, org_id=user.org_id, user_id=user.id)


@router.delete("/{memory_id}")
async def api_delete(
    memory_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    ok = await svc.delete_memory(db, org_id=user.org_id, memory_id=memory_id)
    if not ok:
        raise HTTPException(404, "memory not found")
    return {"deleted": True}
