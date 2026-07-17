"""E2.7 · Marketplace monetization service — pricing + purchase flow.

Encapsulates:
  * upsert / retire pricing plans on a listing
  * compute total & split (platform fee vs vendor payout)
  * create purchase orders in ``pending``
  * transition to ``paid`` (activate) / ``cancelled`` / ``refunded``
  * simple revenue aggregation for a listing / vendor
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.marketplace_monetization import (
    ModelListingPrice,
    ModelPurchaseOrder,
    VALID_BILLING_MODES,
    VALID_PURCHASE_STATUSES,
)


class MonetizationError(Exception):
    """Domain error, mapped to HTTP 400/404/409 at REST layer."""


# ---------------------------------------------------------------------------
# Pricing plans
# ---------------------------------------------------------------------------

async def upsert_price(
    db: AsyncSession,
    *,
    listing_id: uuid.UUID,
    plan_code: str,
    plan_name: str,
    billing_mode: str,
    unit_price_cny_cents: int,
    included_quota: int = 0,
    billing_cycle_days: int | None = None,
    platform_fee_bps: int = 1500,
    note: str | None = None,
) -> ModelListingPrice:
    if billing_mode not in VALID_BILLING_MODES:
        raise MonetizationError(f"invalid billing_mode: {billing_mode}")
    if unit_price_cny_cents < 0:
        raise MonetizationError("unit_price_cny_cents must be >= 0")
    if platform_fee_bps < 0 or platform_fee_bps > 10000:
        raise MonetizationError("platform_fee_bps must be in [0, 10000]")
    if billing_mode == "subscription" and not billing_cycle_days:
        raise MonetizationError(
            "subscription plans require billing_cycle_days"
        )
    plan_code = plan_code.strip()
    if not plan_code:
        raise MonetizationError("plan_code is required")

    q = select(ModelListingPrice).where(
        ModelListingPrice.listing_id == listing_id,
        ModelListingPrice.plan_code == plan_code,
    )
    existing = (await db.execute(q)).scalar_one_or_none()
    if existing is not None:
        existing.plan_name = plan_name
        existing.billing_mode = billing_mode
        existing.unit_price_cny_cents = unit_price_cny_cents
        existing.included_quota = included_quota
        existing.billing_cycle_days = billing_cycle_days
        existing.platform_fee_bps = platform_fee_bps
        existing.note = note
        existing.retired = False
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return existing

    row = ModelListingPrice(
        listing_id=listing_id,
        plan_code=plan_code,
        plan_name=plan_name.strip(),
        billing_mode=billing_mode,
        unit_price_cny_cents=unit_price_cny_cents,
        included_quota=included_quota,
        billing_cycle_days=billing_cycle_days,
        platform_fee_bps=platform_fee_bps,
        note=note,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_prices(
    db: AsyncSession,
    *,
    listing_id: uuid.UUID,
    include_retired: bool = False,
) -> list[ModelListingPrice]:
    q = select(ModelListingPrice).where(
        ModelListingPrice.listing_id == listing_id,
    )
    if not include_retired:
        q = q.where(ModelListingPrice.retired.is_(False))
    q = q.order_by(ModelListingPrice.created_at.asc())
    return list((await db.execute(q)).scalars().all())


async def get_price(
    db: AsyncSession, *, price_id: uuid.UUID,
) -> ModelListingPrice | None:
    q = select(ModelListingPrice).where(ModelListingPrice.id == price_id)
    return (await db.execute(q)).scalar_one_or_none()


async def retire_price(
    db: AsyncSession, *, price_id: uuid.UUID,
) -> bool:
    row = await get_price(db, price_id=price_id)
    if row is None:
        return False
    row.retired = True
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

def _compute_split(
    unit_price: int, units: int, platform_fee_bps: int,
) -> tuple[int, int, int]:
    """Return (total, platform_fee, vendor_payout) in CNY cents."""
    total = unit_price * units
    fee = (total * platform_fee_bps) // 10000
    payout = total - fee
    return total, fee, payout


async def create_order(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    price_id: uuid.UUID,
    units: int = 1,
    external_ref: str | None = None,
) -> ModelPurchaseOrder:
    if units < 1:
        raise MonetizationError("units must be >= 1")
    price = await get_price(db, price_id=price_id)
    if price is None:
        raise MonetizationError("pricing plan not found")
    if price.retired:
        raise MonetizationError("pricing plan has been retired")

    total, fee, payout = _compute_split(
        price.unit_price_cny_cents, units, price.platform_fee_bps,
    )
    order = ModelPurchaseOrder(
        org_id=org_id,
        user_id=user_id,
        listing_id=price.listing_id,
        price_id=price.id,
        plan_code=price.plan_code,
        billing_mode=price.billing_mode,
        units=units,
        total_cny_cents=total,
        platform_fee_cny_cents=fee,
        vendor_payout_cny_cents=payout,
        status="pending",
        external_ref=external_ref,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def get_order(
    db: AsyncSession, *, org_id: uuid.UUID, order_id: uuid.UUID,
) -> ModelPurchaseOrder | None:
    q = select(ModelPurchaseOrder).where(
        ModelPurchaseOrder.id == order_id,
        ModelPurchaseOrder.org_id == org_id,
    )
    return (await db.execute(q)).scalar_one_or_none()


async def list_orders(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    status_: str | None = None,
    limit: int = 100,
) -> list[ModelPurchaseOrder]:
    q = select(ModelPurchaseOrder).where(
        ModelPurchaseOrder.org_id == org_id,
    )
    if status_ is not None:
        if status_ not in VALID_PURCHASE_STATUSES:
            raise MonetizationError(f"invalid status filter: {status_}")
        q = q.where(ModelPurchaseOrder.status == status_)
    q = q.order_by(ModelPurchaseOrder.created_at.desc()).limit(limit)
    return list((await db.execute(q)).scalars().all())


async def mark_paid(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    external_ref: str | None = None,
) -> ModelPurchaseOrder:
    row = await get_order(db, org_id=org_id, order_id=order_id)
    if row is None:
        raise MonetizationError("order not found")
    if row.status != "pending":
        raise MonetizationError(
            f"cannot mark paid from status {row.status!r}",
        )
    now = datetime.now(timezone.utc)
    row.status = "paid"
    row.activated_at = now
    if external_ref:
        row.external_ref = external_ref
    # For subscription plans, compute the expiry.
    if row.billing_mode == "subscription":
        price = await get_price(db, price_id=row.price_id)
        cycle = price.billing_cycle_days if price else None
        if cycle:
            row.expires_at = now + timedelta(days=cycle * row.units)
    row.updated_at = now
    await db.commit()
    await db.refresh(row)
    return row


async def cancel_order(
    db: AsyncSession, *, org_id: uuid.UUID, order_id: uuid.UUID,
) -> ModelPurchaseOrder:
    row = await get_order(db, org_id=org_id, order_id=order_id)
    if row is None:
        raise MonetizationError("order not found")
    if row.status != "pending":
        raise MonetizationError(
            f"cannot cancel from status {row.status!r}",
        )
    row.status = "cancelled"
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def refund_order(
    db: AsyncSession, *, org_id: uuid.UUID, order_id: uuid.UUID,
) -> ModelPurchaseOrder:
    row = await get_order(db, org_id=org_id, order_id=order_id)
    if row is None:
        raise MonetizationError("order not found")
    if row.status != "paid":
        raise MonetizationError(
            f"cannot refund from status {row.status!r}",
        )
    row.status = "refunded"
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Revenue aggregation
# ---------------------------------------------------------------------------

async def revenue_by_listing(
    db: AsyncSession, *, listing_id: uuid.UUID,
) -> dict[str, Any]:
    q = select(
        func.count(ModelPurchaseOrder.id),
        func.coalesce(func.sum(ModelPurchaseOrder.total_cny_cents), 0),
        func.coalesce(func.sum(ModelPurchaseOrder.platform_fee_cny_cents), 0),
        func.coalesce(func.sum(ModelPurchaseOrder.vendor_payout_cny_cents), 0),
    ).where(
        ModelPurchaseOrder.listing_id == listing_id,
        ModelPurchaseOrder.status == "paid",
    )
    r = (await db.execute(q)).one()
    return {
        "listing_id": str(listing_id),
        "paid_orders": int(r[0] or 0),
        "gross_cny_cents": int(r[1] or 0),
        "platform_fee_cny_cents": int(r[2] or 0),
        "vendor_payout_cny_cents": int(r[3] or 0),
    }
