"""F4.2 · Copilot prompt template admin REST."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models.user import User
from app.services.copilot_prompt_template import (
    PromptTemplateError, activate_version, create_version,
    diff_versions, get_active, get_version, list_versions,
    rollback_to_previous,
)


router = APIRouter(
    prefix="/copilot/prompt-templates",
    tags=["copilot-prompt-templates"],
)


class TemplateIn(BaseModel):
    persona: str = Field(..., description="operator|analyst|instructor")
    name: str = Field(..., min_length=1, max_length=128)
    system_prompt: str = Field(..., min_length=1, max_length=16000)
    notes: str | None = Field(None, max_length=4000)
    activate: bool = False


def _map(exc: PromptTemplateError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


@router.post("", status_code=201)
async def api_create(
    body: TemplateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "owner")),
) -> dict[str, Any]:
    try:
        return await create_version(
            db,
            persona=body.persona,
            name=body.name,
            system_prompt=body.system_prompt,
            notes=body.notes,
            activate=body.activate,
            created_by=user.id,
        )
    except PromptTemplateError as e:
        raise _map(e)


@router.post(
    "/{persona}/versions/{version}/activate", status_code=200,
)
async def api_activate(
    persona: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner")),
) -> dict[str, Any]:
    try:
        return await activate_version(
            db, persona=persona, version=version,
        )
    except PromptTemplateError as e:
        raise _map(e)


@router.post("/{persona}/rollback", status_code=200)
async def api_rollback(
    persona: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin", "owner")),
) -> dict[str, Any]:
    try:
        r = await rollback_to_previous(db, persona=persona)
    except PromptTemplateError as e:
        raise _map(e)
    if r is None:
        raise HTTPException(
            404, "no earlier version available for rollback",
        )
    return r


@router.get("")
async def api_list(
    persona: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    try:
        return await list_versions(
            db, persona=persona, limit=limit, offset=offset,
        )
    except PromptTemplateError as e:
        raise _map(e)


@router.get("/{persona}/active")
async def api_get_active(
    persona: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        r = await get_active(db, persona=persona)
    except PromptTemplateError as e:
        raise _map(e)
    if r is None:
        raise HTTPException(404, "no active template for persona")
    return r


@router.get("/{persona}/versions/{version}")
async def api_get_version(
    persona: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    r = await get_version(db, persona=persona, version=version)
    if r is None:
        raise HTTPException(404, "version not found")
    return r


@router.get(
    "/{persona}/diff/{from_version}/{to_version}",
)
async def api_diff(
    persona: str,
    from_version: int,
    to_version: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await diff_versions(
            db, persona=persona,
            from_version=from_version,
            to_version=to_version,
        )
    except PromptTemplateError as e:
        raise _map(e)
