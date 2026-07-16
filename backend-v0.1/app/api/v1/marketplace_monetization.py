"""E2.7 · Marketplace monetization REST endpoints.

POST   /marketplace/listings/{lid}/prices     upsert plan
GET    /marketplace/listings/{lid}/prices     list plans (active only by default)
DELETE /marketplace/prices/{pid}              retire plan (soft)
GET    /marketplace/listings/{lid}/revenue    revenue rollup (paid only)

POST   /marketplace/orders                    create pending order
GET    /marketplace/orders                    list my org's orders
GET    /marketplace/orders/{oid}              fetch one (org-scoped)
POST   /marketplace/orders/{oid}/pay          transition -> paid
POST   /marketplace/orders/{oid}/cancel       transition -> cancelled
POST   /marketplace/orders/{oid}/refund       transition -> refunded
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
from app.services.marketplace_monetization import (
    MonetizationError,
    cancel_order,
    create_order,
    get_order,
    list_orders,
    list_prices,
    mark_paid,
    refund_order,
    retire_price,
    revenue_by_listing,
    upsert_price,
)


router = APIRouter(
    prefix="/marketplace",
    tags=["marketplace-monetization"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PriceOut(BaseModel):
    id: UUID
    listing_id: UUID
    plan_code: str
    plan_name: str
    billing_mode: str
    unit_price_cny_cents: int
    included_quota: int
    billing_cycle_days: int | None
    platform_fee_bps: int
    currency: str
    retired: bool
    note: str | None
    created_at: str

    @classmethod
    def from_row(cls, r) -> "PriceOut":
        return cls(
            id=r.id,
            listing_id=r.listing_id,
            plan_code=r.plan_code,
            plan_name=r.plan_name,
            billing_mode=r.billing_mode,
            unit_price_cny_cents=r.unit_price_cny_cents,
            included_quota=r.included_quota,
            billing_cycle_days=r.billing_cycle_days,
            platform_fee_bps=r.platform_fee_bps,
            currency=r.currency,
            retired=r.retired,
            note=r.note,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )


class UpsertPricePayload(BaseModel):
    plan_code: str = Field(..., min_length=1, max_length=64)
    plan_name: str = Field(..., min_length=1, max_length=128)
    billing_mode: str = Field(..., min_length=1, max_length=24)
    unit_price_cny_cents: int = Field(..., ge=0)
    included_quota: int = 0
    billing_cycle_days: int | None = None
    platform_fee_bps: int = 1500
    note: str | None = None


class OrderOut(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID
    listing_id: UUID
    price_id: UUID
    plan_code: str
    billing_mode: str
    units: int
    total_cny_cents: int
    platform_fee_cny_cents: int
    vendor_payout_cny_cents: int
    status: str
    external_ref: str | None
    activated_at: str | None
    expires_at: str | None
    created_at: str

    @classmethod
    def from_row(cls, r) -> "OrderOut":
        return cls(
            id=r.id,
            org_id=r.org_id,
            user_id=r.user_id,
            listing_id=r.listing_id,
            price_id=r.price_id,
            plan_code=r.plan_code,
            billing_mode=r.billing_mode,
            units=r.units,
            total_cny_cents=r.total_cny_cents,
            platform_fee_cny_cents=r.platform_fee_cny_cents,
            vendor_payout_cny_cents=r.vendor_payout_cny_cents,
            status=r.status,
            external_ref=r.external_ref,
            activated_at=(
                r.activated_at.isoformat() if r.activated_at else None
            ),
            expires_at=r.expires_at.isoformat() if r.expires_at else None,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )


class CreateOrderPayload(BaseModel):
    price_id: UUID
    units: int = Field(1, ge=1)
    external_ref: str | None = None


class PayOrderPayload(BaseModel):
    external_ref: str | None = None


def _map(exc: MonetizationError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg:
        return HTTPException(404, msg)
    return HTTPException(400, msg)


# ---------------------------------------------------------------------------
# Pricing plan endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/listings/{lid}/prices",
    response_model=PriceOut,
    status_code=201,
)
async def api_upsert_price(
    lid: UUID,
    payload: UpsertPricePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PriceOut:
    try:
        row = await upsert_price(
            db,
            listing_id=lid,
            plan_code=payload.plan_code,
            plan_name=payload.plan_name,
            billing_mode=payload.billing_mode,
            unit_price_cny_cents=payload.unit_price_cny_cents,
            included_quota=payload.included_quota,
            billing_cycle_days=payload.billing_cycle_days,
            platform_fee_bps=payload.platform_fee_bps,
            note=payload.note,
        )
    except MonetizationError as exc:
        raise _map(exc)
    return PriceOut.from_row(row)


@router.get(
    "/listings/{lid}/prices", response_model=list[PriceOut],
)
async def api_list_prices(
    lid: UUID,
    include_retired: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PriceOut]:
    rows = await list_prices(
        db, listing_id=lid, include_retired=include_retired,
    )
    return [PriceOut.from_row(r) for r in rows]


@router.delete("/prices/{price_id}", status_code=204)
async def api_retire_price(
    price_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    ok = await retire_price(db, price_id=price_id)
    if not ok:
        raise HTTPException(404, "pricing plan not found")


@router.get("/listings/{lid}/revenue")
async def api_revenue(
    lid: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await revenue_by_listing(db, listing_id=lid)


# ---------------------------------------------------------------------------
# Purchase order endpoints
# ---------------------------------------------------------------------------

@router.post("/orders", response_model=OrderOut, status_code=201)
async def api_create_order(
    payload: CreateOrderPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderOut:
    try:
        row = await create_order(
            db,
            org_id=user.org_id,
            user_id=user.id,
            price_id=payload.price_id,
            units=payload.units,
            external_ref=payload.external_ref,
        )
    except MonetizationError as exc:
        raise _map(exc)
    return OrderOut.from_row(row)


@router.get("/orders", response_model=list[OrderOut])
async def api_list_orders(
    status_: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OrderOut]:
    try:
        rows = await list_orders(
            db, org_id=user.org_id, status_=status_,
            limit=min(max(limit, 1), 500),
        )
    except MonetizationError as exc:
        raise _map(exc)
    return [OrderOut.from_row(r) for r in rows]


@router.get("/orders/{order_id}", response_model=OrderOut)
async def api_get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderOut:
    row = await get_order(db, org_id=user.org_id, order_id=order_id)
    if row is None:
        raise HTTPException(404, "order not found")
    return OrderOut.from_row(row)


@router.post("/orders/{order_id}/pay", response_model=OrderOut)
async def api_pay_order(
    order_id: UUID,
    payload: PayOrderPayload | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderOut:
    try:
        row = await mark_paid(
            db, org_id=user.org_id, order_id=order_id,
            external_ref=(payload.external_ref if payload else None),
        )
    except MonetizationError as exc:
        raise _map(exc)
    return OrderOut.from_row(row)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def api_cancel_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderOut:
    try:
        row = await cancel_order(db, org_id=user.org_id, order_id=order_id)
    except MonetizationError as exc:
        raise _map(exc)
    return OrderOut.from_row(row)


@router.post("/orders/{order_id}/refund", response_model=OrderOut)
async def api_refund_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderOut:
    try:
        row = await refund_order(db, org_id=user.org_id, order_id=order_id)
    except MonetizationError as exc:
        raise _map(exc)
    return OrderOut.from_row(row)
