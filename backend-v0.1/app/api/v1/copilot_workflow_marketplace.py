"""API: /copilot/workflow-marketplace — E2.6 Workflow 市场."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services import copilot_workflow_marketplace as svc

router = APIRouter(
    prefix="/copilot/workflow-marketplace",
    tags=["copilot-workflow-marketplace"],
)


class PublishIn(BaseModel):
    workflow_id: UUID
    title: str = Field(..., min_length=1, max_length=128)
    summary: str = Field(default="", max_length=2048)
    tags: list[str] | None = None
    visibility: str = "public"


class RateIn(BaseModel):
    stars: int = Field(..., ge=1, le=5)
    comment: str | None = None


class InstallIn(BaseModel):
    new_name: str | None = None


@router.post("/publish", response_model=dict[str, Any])
async def api_publish(
    body: PublishIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        listing = await svc.publish_workflow(
            db,
            svc.PublishRequest(
                workflow_id=body.workflow_id,
                author_user_id=user.id,
                org_id=user.org_id,
                title=body.title,
                summary=body.summary,
                tags=body.tags,
                visibility=body.visibility,
            ),
        )
    except svc.MarketplaceError as e:
        raise HTTPException(400, str(e))
    return svc.listing_to_dict(listing)


@router.post("/listings/{listing_id}/unpublish", status_code=204, response_model=None)
async def api_unpublish(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        await svc.unpublish_listing(
            db, listing_id=listing_id,
            actor_user_id=user.id, actor_org_id=user.org_id,
        )
    except svc.MarketplaceError as e:
        raise HTTPException(400, str(e))
    from fastapi import Response
    return Response(status_code=204)


@router.get("/listings", response_model=dict[str, Any])
async def api_browse(
    q: str | None = None,
    tag: str | None = None,
    order_by: str = Query("install_count", pattern="^(install_count|avg_rating|published_at)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rows, total = await svc.browse_listings(
        db, viewer_org_id=user.org_id,
        query=q, tag=tag, order_by=order_by,
        limit=limit, offset=offset,
    )
    return {
        "total": total,
        "items": [svc.listing_to_dict(r) for r in rows],
    }


@router.get("/listings/{listing_id}", response_model=dict[str, Any])
async def api_get_listing(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        listing = await svc.get_listing(
            db, listing_id=listing_id, viewer_org_id=user.org_id,
        )
    except svc.MarketplaceError as e:
        raise HTTPException(404, str(e))
    d = svc.listing_to_dict(listing)
    d["dsl_yaml_snapshot"] = listing.dsl_yaml_snapshot
    return d


@router.post("/listings/{listing_id}/install", response_model=dict[str, Any])
async def api_install(
    listing_id: UUID,
    body: InstallIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        r = await svc.install_listing(
            db, listing_id=listing_id,
            installer_user_id=user.id, installer_org_id=user.org_id,
            new_name=body.new_name,
        )
    except svc.MarketplaceError as e:
        raise HTTPException(400, str(e))
    return {
        "workflow_id": str(r.new_workflow.id),
        "workflow_name": r.new_workflow.name,
        "install_id": str(r.install.id),
        "listing_install_count": r.listing.install_count,
    }


@router.post("/listings/{listing_id}/rate", response_model=dict[str, Any])
async def api_rate(
    listing_id: UUID,
    body: RateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        row = await svc.rate_listing(
            db, listing_id=listing_id,
            rater_user_id=user.id, rater_org_id=user.org_id,
            stars=body.stars, comment=body.comment,
        )
    except svc.MarketplaceError as e:
        raise HTTPException(400, str(e))
    return svc.rating_to_dict(row)


@router.get("/listings/{listing_id}/ratings", response_model=dict[str, Any])
async def api_list_ratings(
    listing_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    # Access check via get_listing
    try:
        await svc.get_listing(db, listing_id=listing_id, viewer_org_id=user.org_id)
    except svc.MarketplaceError as e:
        raise HTTPException(404, str(e))
    rows = await svc.list_ratings(db, listing_id=listing_id, limit=limit, offset=offset)
    return {"items": [svc.rating_to_dict(r) for r in rows]}


@router.get("/listings/{listing_id}/my-rating", response_model=dict[str, Any] | None)
async def api_my_rating(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any] | None:
    row = await svc.get_my_rating(
        db, listing_id=listing_id, rater_user_id=user.id,
    )
    return svc.rating_to_dict(row) if row else None


@router.get("/listings/{listing_id}/installs", response_model=dict[str, Any])
async def api_list_installs(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Author-only analytics: who installed this listing."""
    try:
        rows = await svc.list_installs_of(
            db, listing_id=listing_id, actor_user_id=user.id,
        )
    except svc.MarketplaceError as e:
        raise HTTPException(403, str(e))
    return {
        "items": [
            {
                "id": str(r.id),
                "installer_user_id": str(r.installer_user_id),
                "installer_org_id": str(r.installer_org_id) if r.installer_org_id else None,
                "new_workflow_id": str(r.new_workflow_id),
                "installed_at": r.installed_at.isoformat() if r.installed_at else None,
            }
            for r in rows
        ]
    }
