"""Model Marketplace API endpoints — v2.2 E5 Model Marketplace.

Implements:
- GET /model-marketplace/models — list/search public models
- POST /model-marketplace/models — create new model (author)
- GET /model-marketplace/models/{id} — detail
- PUT /model-marketplace/models/{id} — update (author-only)
- DELETE /model-marketplace/models/{id} — delete (author / admin)
- POST /model-marketplace/models/{id}/purchase — purchase (billed via platform)
- GET /model-marketplace/my — list my published / purchased
- POST /model-marketplace/{id}/review — add review
"""
from __future__ import annotations

from typing import Annotated, Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.model_marketplace import (
    ModelListing, ModelListingReview,
)
from app.models.user import User


router = APIRouter(prefix="/model-marketplace", tags=["model-marketplace"])


# ---------- Schemas ---------------------------------------------------------

class ModelListingOut(BaseModel):
    id: UUID
    author_id: Optional[UUID]
    org_id: Optional[UUID]
    name: str
    description: str
    category: str  # "detect", "segment", "pose", "planning", "gs", "other"
    license_type: str  # "free", "one-time", "subscription"
    price_cents: Optional[int]
    revenue_split_author: int  # percentage, default 70
    tags: Optional[List[str]]
    average_rating: Optional[float]
    review_count: int
    download_count: int
    purchase_count: int
    published: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class CreateModelRequest(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    description: str = Field(min_length=10)
    category: str
    license_type: str = Field(description="'free' | 'one-time' | 'subscription'")
    price_cents: Optional[int] = None
    tags: Optional[List[str]] = Field(default_factory=list)
    published: bool = False


class UpdateModelRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=128)
    description: Optional[str] = Field(None, min_length=10)
    category: Optional[str] = None
    price_cents: Optional[int] = None
    tags: Optional[List[str]] = None
    published: Optional[bool] = None


class ModelListingReviewOut(BaseModel):
    id: UUID
    model_id: UUID
    user_id: Optional[UUID]
    rating: int  # 1-5
    comment: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


class CreateReviewRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class PurchaseRequest(BaseModel):
    pass  # no extra fields needed


class PurchaseOut(BaseModel):
    id: UUID
    model_id: UUID
    buyer_id: UUID
    amount_cents: int
    status: str
    created_at: str


class ModelListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[ModelListingOut]


# ---------- Helpers ---------------------------------------------------------


def is_author_or_admin(user: User, model: ModelListing) -> bool:
    if user.role == "admin":
        return True
    if model.author_id == user.id:
        return True
    if model.org_id == user.org_id and user.role in ("system_officer", "admin"):
        return True
    return False


# ---------- Endpoints -------------------------------------------------------


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    author_id: Optional[UUID] = None,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelListResponse:
    """List public published model listings.

    Filter by category, tag, search term, author.
    Only published models are shown publicly; drafts only visible to author.
    """
    offset = (page - 1) * size
    query = select(ModelListing).where(ModelListing.published == True).order_by(
        ModelListing.pinned.desc(),
        desc(ModelListing.created_at),
    )

    if category:
        query = query.where(ModelListing.category == category)
    if tag is not None:
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB
        query = query.where(cast(ModelListing.tags, JSONB).contains([tag]))
    if search is not None and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(
            ModelListing.name.ilike(term),
            ModelListing.description.ilike(term),
        ))
    if author_id is not None:
        query = query.where(ModelListing.author_id == author_id)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    # Fetch
    query = query.offset(offset).limit(size)
    result = await db.execute(query)
    items = result.scalars().all()

    out = [ModelListingOut.model_validate(m) for m in items]
    return ModelListResponse(
        total=total,
        page=page,
        size=size,
        items=out,
    )


@router.get("/models/{model_id}", response_model=ModelListingOut)
async def get_model(
    model_id: UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelListingOut:
    """Get a single model listing by ID."""
    model = (
        await db.execute(select(ModelListing).where(ModelListing.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(404, "model not found")

    if not model.published:
        if current_user is None or not is_author_or_admin(current_user, model):
            raise HTTPException(403, "this draft is not publicly visible")

    return ModelListingOut.model_validate(model)


@router.post("/models", response_model=ModelListingOut)
async def create_model(
    req: CreateModelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelListingOut:
    """Create a new model listing. Author is current user."""
    if req.license_type not in ("free", "one-time", "subscription"):
        raise HTTPException(400, "license_type must be free|one-time|subscription")
    if req.license_type != "free" and (req.price_cents is None or req.price_cents <= 0):
        raise HTTPException(400, "price must be positive for paid license")
    if req.license_type == "free" and req.price_cents is not None:
        # Normalize to zero for free
        req.price_cents = None

    listing = ModelListing(
        author_id=current_user.id,
        org_id=current_user.org_id,
        name=req.name,
        description=req.description,
        category=req.category,
        license_type=req.license_type,
        price_cents=req.price_cents,
        revenue_split_author=70,  # platform default is 70/30
        tags=req.tags,
        published=req.published,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return ModelListingOut.model_validate(listing)


@router.put("/models/{model_id}", response_model=ModelListingOut)
async def update_model(
    model_id: UUID,
    req: UpdateModelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelListingOut:
    """Update an existing model listing (author only)."""
    model = (
        await db.execute(select(ModelListing).where(ModelListing.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(404, "model not found")

    if not is_author_or_admin(current_user, model):
        raise HTTPException(403, "not permitted to update this model")

    if req.name is not None:
        model.name = req.name
    if req.description is not None:
        model.description = req.description
    if req.category is not None:
        model.category = req.category
    if req.price_cents is not None:
        model.price_cents = req.price_cents if req.price_cents > 0 else None
    if req.tags is not None:
        model.tags = req.tags
    if req.published is not None:
        model.published = req.published

    await db.commit()
    await db.refresh(model)
    return ModelListingOut.model_validate(model)


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a model listing (author or admin)."""
    model = (
        await db.execute(select(ModelListing).where(ModelListing.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(404, "model not found")

    if not is_author_or_admin(current_user, model):
        raise HTTPException(403, "not permitted to delete this model")

    await db.delete(model)
    await db.commit()


@router.get("/my", response_model=List[ModelListingOut])
async def list_my_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ModelListingOut]:
    """List all models authored by current user (including drafts)."""
    query = (
        select(ModelListing)
        .where(ModelListing.author_id == current_user.id)
        .order_by(desc(ModelListing.created_at))
    )
    result = await db.execute(query)
    items = result.scalars().all()
    return [ModelListingOut.model_validate(m) for m in items]


@router.post("/models/{model_id}/purchase", response_model=PurchaseOut)
async def purchase_model(
    model_id: UUID,
    req: PurchaseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PurchaseOut:
    """Purchase a paid model. Creates purchase record, records split for payout."""
    model = (
        await db.execute(select(ModelListing).where(ModelListing.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(404, "model not found")
    if not model.published:
        raise HTTPException(400, "model is not published for purchase")

    # Check if already purchased
    existing = (
        await db.execute(
            select(ModelPurchase).where(
                ModelPurchase.model_id == model_id,
                ModelPurchase.buyer_id == current_user.id,
                ModelPurchase.status == "completed",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Already purchased, just return the existing record
        return PurchaseOut.model_validate(existing)

    if model.license_type == "free":
        # Free: zero amount, always completed
        amount_cents = 0
        status = "completed"
    else:
        # TODO: integrate payment processor
        # For MVP: record purchase as pending completion, user is expected to pay
        # off-platform or via admin confirmation
        amount_cents = model.price_cents or 0
        status = "pending"

    purchase = ModelPurchase(
        model_id=model_id,
        buyer_id=current_user.id,
        amount_cents=amount_cents,
        status=status,
    )
    db.add(purchase)

    # Increment purchase count on model
    model.purchase_count += 1

    await db.commit()
    await db.refresh(purchase)
    return PurchaseOut.model_validate(purchase)


@router.get("/models/{model_id}/reviews", response_model=List[ModelListingReviewOut])
async def list_reviews(
    model_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> List[ModelListingReviewOut]:
    """List all reviews for a model."""
    query = (
        select(ModelListingReview)
        .where(ModelListingReview.model_id == model_id)
        .order_by(desc(ModelListingReview.created_at))
    )
    result = await db.execute(query)
    reviews = result.scalars().all()
    return [ModelListingReviewOut.model_validate(r) for r in reviews]


@router.post("/models/{model_id}/reviews", response_model=ModelListingReviewOut)
async def create_review(
    model_id: UUID,
    req: CreateReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelListingReviewOut:
    """Add or update a review/rating for a purchased model."""
    model = (
        await db.execute(select(ModelListing).where(ModelListing.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(404, "model not found")

    # Must have purchased to review
    has_purchased = (
        await db.execute(
            select(ModelPurchase).where(
                ModelPurchase.model_id == model_id,
                ModelPurchase.buyer_id == current_user.id,
                ModelPurchase.status == "completed",
            )
        )
    ).scalar_one_or_none()
    if has_purchased is None and model.license_type != "free":
        raise HTTPException(403, "you must purchase this model before reviewing")

    # Check if existing review
    existing = (
        await db.execute(
            select(ModelListingReview).where(
                ModelListingReview.model_id == model_id,
                ModelListingReview.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.rating = req.rating
        existing.comment = req.comment
    else:
        review = ModelListingReview(
            model_id=model_id,
            user_id=current_user.id,
            rating=req.rating,
            comment=req.comment,
        )
        db.add(review)

    await db.commit()
    # Recompute average rating on model
    await recompute_average_rating(model_id, db)
    await db.refresh(model if existing is None else existing)

    out = existing if existing is not None else review
    return ModelListingReviewOut.model_validate(out)


async def recompute_average_rating(model_id: UUID, db: AsyncSession) -> None:
    """Recompute average rating for a model after new review."""
    model = (
        await db.execute(select(ModelListing).where(ModelListing.id == model_id))
    ).scalar_one_or_none()
    if model is None:
        return
    avg_q = select(func.avg(ModelListingReview.rating)).where(ModelListingReview.model_id == model_id)
    avg = (await db.execute(avg_q)).scalar_one_or_none()
    cnt_q = select(func.count(ModelListingReview.id)).where(ModelListingReview.model_id == model_id)
    cnt = (await db.execute(cnt_q)).scalar_one_or_none()
    if model:
        model.average_rating = float(avg) if avg is not None else None
        model.review_count = int(cnt) if cnt is not None else 0
