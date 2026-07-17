"""D2.2 · Scene annotation REST endpoints.

Layered under ``/scenes/{sid}/annotations`` for scene-scoped operations,
and ``/annotations/{ann_id}`` for single-entry ops + replies.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.scene_annotation import (
    AnnotationError,
    create_annotation,
    create_reply,
    delete_annotation,
    get_annotation,
    list_by_scene,
    list_replies,
    stats_by_scene,
    summarize_geometry,
    update_annotation,
)


router = APIRouter(tags=["scene-annotation"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AnnotationOut(BaseModel):
    id: UUID
    scene_id: UUID
    org_id: UUID
    author_id: UUID
    geom_kind: str
    geom_vertices: list[Any]
    color: str
    label: str
    description: str | None
    severity: str
    frame_index: int | None
    layer: str
    meta: dict[str, Any]
    resolved: bool
    geometry_summary: dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, r) -> "AnnotationOut":
        return cls(
            id=r.id,
            scene_id=r.scene_id,
            org_id=r.org_id,
            author_id=r.author_id,
            geom_kind=r.geom_kind,
            geom_vertices=r.geom_vertices,
            color=r.color,
            label=r.label,
            description=r.description,
            severity=r.severity,
            frame_index=r.frame_index,
            layer=r.layer,
            meta=r.meta or {},
            resolved=r.resolved,
            geometry_summary=summarize_geometry(r.geom_kind, r.geom_vertices),
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )


class CreatePayload(BaseModel):
    geom_kind: str = Field(..., min_length=1, max_length=16)
    geom_vertices: list[Any]
    label: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    color: str = Field("#22d3ee", min_length=1, max_length=9)
    severity: str = "info"
    frame_index: int | None = None
    layer: str = "default"
    meta: dict[str, Any] | None = None


class UpdatePayload(BaseModel):
    label: str | None = None
    description: str | None = None
    color: str | None = None
    severity: str | None = None
    resolved: bool | None = None
    layer: str | None = None
    meta: dict[str, Any] | None = None


class ReplyOut(BaseModel):
    id: UUID
    annotation_id: UUID
    author_id: UUID
    body: str
    created_at: str

    @classmethod
    def from_row(cls, r) -> "ReplyOut":
        return cls(
            id=r.id,
            annotation_id=r.annotation_id,
            author_id=r.author_id,
            body=r.body,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )


class ReplyPayload(BaseModel):
    body: str = Field(..., min_length=1)


def _map(exc: AnnotationError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


# ---------------------------------------------------------------------------
# Scene-scoped endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/scenes/{scene_id}/annotations",
    response_model=AnnotationOut,
    status_code=201,
)
async def api_create_annotation(
    scene_id: UUID,
    payload: CreatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnnotationOut:
    try:
        row = await create_annotation(
            db,
            scene_id=scene_id,
            org_id=user.org_id,
            author_id=user.id,
            geom_kind=payload.geom_kind,
            geom_vertices=payload.geom_vertices,
            label=payload.label,
            description=payload.description,
            color=payload.color,
            severity=payload.severity,
            frame_index=payload.frame_index,
            layer=payload.layer,
            meta=payload.meta,
        )
    except AnnotationError as exc:
        raise _map(exc)
    return AnnotationOut.from_row(row)


@router.get(
    "/scenes/{scene_id}/annotations",
    response_model=list[AnnotationOut],
)
async def api_list_annotations(
    scene_id: UUID,
    layer: str | None = None,
    severity: str | None = None,
    only_unresolved: bool = False,
    frame_index: int | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AnnotationOut]:
    try:
        rows = await list_by_scene(
            db,
            org_id=user.org_id,
            scene_id=scene_id,
            layer=layer,
            severity=severity,
            only_unresolved=only_unresolved,
            frame_index=frame_index,
        )
    except AnnotationError as exc:
        raise _map(exc)
    return [AnnotationOut.from_row(r) for r in rows]


@router.get("/scenes/{scene_id}/annotation-stats")
async def api_annotation_stats(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await stats_by_scene(
        db, org_id=user.org_id, scene_id=scene_id,
    )


# ---------------------------------------------------------------------------
# Annotation-scoped endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/annotations/{ann_id}", response_model=AnnotationOut,
)
async def api_get_annotation(
    ann_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnnotationOut:
    row = await get_annotation(db, org_id=user.org_id, ann_id=ann_id)
    if row is None:
        raise HTTPException(404, "annotation not found")
    return AnnotationOut.from_row(row)


@router.patch(
    "/annotations/{ann_id}", response_model=AnnotationOut,
)
async def api_update_annotation(
    ann_id: UUID,
    payload: UpdatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnnotationOut:
    try:
        row = await update_annotation(
            db,
            org_id=user.org_id, ann_id=ann_id,
            label=payload.label,
            description=payload.description,
            color=payload.color,
            severity=payload.severity,
            resolved=payload.resolved,
            layer=payload.layer,
            meta=payload.meta,
        )
    except AnnotationError as exc:
        raise _map(exc)
    return AnnotationOut.from_row(row)


@router.delete("/annotations/{ann_id}", status_code=204)
async def api_delete_annotation(
    ann_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    ok = await delete_annotation(
        db, org_id=user.org_id, ann_id=ann_id,
    )
    if not ok:
        raise HTTPException(404, "annotation not found")


@router.post(
    "/annotations/{ann_id}/replies",
    response_model=ReplyOut,
    status_code=201,
)
async def api_create_reply(
    ann_id: UUID,
    payload: ReplyPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReplyOut:
    try:
        row = await create_reply(
            db,
            org_id=user.org_id,
            annotation_id=ann_id,
            author_id=user.id,
            body=payload.body,
        )
    except AnnotationError as exc:
        raise _map(exc)
    return ReplyOut.from_row(row)


@router.get(
    "/annotations/{ann_id}/replies",
    response_model=list[ReplyOut],
)
async def api_list_replies(
    ann_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ReplyOut]:
    try:
        rows = await list_replies(
            db, org_id=user.org_id, annotation_id=ann_id,
        )
    except AnnotationError as exc:
        raise _map(exc)
    return [ReplyOut.from_row(r) for r in rows]
