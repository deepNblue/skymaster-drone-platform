"""D2.4 · Annotation semantic search REST — Copilot Agent 二期."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.annotation_search import (
    parse_query, search_annotations, suggest_annotation_from_query,
)
from app.api.v1.scene_annotation import AnnotationOut


router = APIRouter(prefix="/annotation-search", tags=["scene-annotation"])


class SearchHit(BaseModel):
    annotation: AnnotationOut
    score: int
    matched_reasons: list[str]


class SearchOut(BaseModel):
    parsed: dict[str, Any]
    hits: list[SearchHit]


class SuggestOut(BaseModel):
    query: str
    suggestion: dict[str, Any] | None


@router.get("/scenes/{scene_id}", response_model=SearchOut)
async def api_search(
    scene_id: UUID,
    q: str = Query("", alias="query"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SearchOut:
    parsed = parse_query(q)
    parsed_out = {
        "raw": parsed["raw"],
        "keywords": parsed["keywords"],
        "geom_kinds": sorted(parsed["geom_kinds"]),
        "severities": sorted(parsed["severities"]),
        "layers": sorted(parsed["layers"]),
    }
    hits = await search_annotations(
        db,
        org_id=user.org_id,
        scene_id=scene_id,
        query=q,
        limit=limit,
    )
    hit_out = [
        SearchHit(
            annotation=AnnotationOut.from_row(h["annotation"]),
            score=h["score"],
            matched_reasons=h["matched_reasons"],
        )
        for h in hits
    ]
    return SearchOut(parsed=parsed_out, hits=hit_out)


@router.get("/suggest", response_model=SuggestOut)
async def api_suggest(
    q: str = Query("", alias="query"),
    _user: User = Depends(get_current_user),
) -> SuggestOut:
    return SuggestOut(
        query=q,
        suggestion=suggest_annotation_from_query(q),
    )
