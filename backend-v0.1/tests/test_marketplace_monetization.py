"""E2.7 · Marketplace monetization tests — pricing + purchase orders."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"mm+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=org, role="user")
    return tok, uid, org


async def _mkprice(
    client, tok: str, lid: UUID, **kwargs
) -> dict:
    payload = {
        "plan_code": "monthly",
        "plan_name": "月度订阅",
        "billing_mode": "subscription",
        "unit_price_cny_cents": 9900,
        "billing_cycle_days": 30,
        "platform_fee_bps": 1500,
    }
    payload.update(kwargs)
    r = await client.post(
        f"/api/v1/marketplace/listings/{lid}/prices",
        headers=_h(tok), json=payload,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_upsert_and_list_price(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(client, tok, lid)
    assert p["unit_price_cny_cents"] == 9900
    assert p["billing_mode"] == "subscription"
    assert p["retired"] is False

    r = await client.get(
        f"/api/v1/marketplace/listings/{lid}/prices", headers=_h(tok),
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_upsert_updates_existing_plan(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p1 = await _mkprice(client, tok, lid, unit_price_cny_cents=9900)
    p2 = await _mkprice(client, tok, lid, unit_price_cny_cents=12900)
    # Same id (upsert), price updated.
    assert p1["id"] == p2["id"]
    assert p2["unit_price_cny_cents"] == 12900


async def test_subscription_requires_cycle(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    r = await client.post(
        f"/api/v1/marketplace/listings/{lid}/prices", headers=_h(tok),
        json={
            "plan_code": "no-cycle",
            "plan_name": "bad",
            "billing_mode": "subscription",
            "unit_price_cny_cents": 100,
        },
    )
    assert r.status_code == 400
    assert "billing_cycle_days" in r.text


async def test_invalid_billing_mode_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    r = await client.post(
        f"/api/v1/marketplace/listings/{lid}/prices", headers=_h(tok),
        json={
            "plan_code": "x", "plan_name": "x",
            "billing_mode": "gift",
            "unit_price_cny_cents": 0,
        },
    )
    assert r.status_code == 400


async def test_retire_price_hides_from_default_list(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(client, tok, lid)
    r = await client.delete(
        f"/api/v1/marketplace/prices/{p['id']}", headers=_h(tok),
    )
    assert r.status_code == 204

    r = await client.get(
        f"/api/v1/marketplace/listings/{lid}/prices", headers=_h(tok),
    )
    assert r.json() == []

    r = await client.get(
        f"/api/v1/marketplace/listings/{lid}/prices"
        "?include_retired=true", headers=_h(tok),
    )
    assert len(r.json()) == 1
    assert r.json()[0]["retired"] is True


async def test_create_order_computes_split(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(
        client, tok, lid,
        unit_price_cny_cents=10000, platform_fee_bps=2000,  # 20%
    )
    r = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok),
        json={"price_id": p["id"], "units": 3},
    )
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["total_cny_cents"] == 30000
    assert o["platform_fee_cny_cents"] == 6000
    assert o["vendor_payout_cny_cents"] == 24000
    assert o["status"] == "pending"


async def test_create_order_rejects_retired_plan(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(client, tok, lid)
    await client.delete(
        f"/api/v1/marketplace/prices/{p['id']}", headers=_h(tok),
    )
    r = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok),
        json={"price_id": p["id"]},
    )
    assert r.status_code == 400
    assert "retired" in r.text.lower()


async def test_pay_activates_subscription_and_sets_expiry(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(
        client, tok, lid, billing_cycle_days=30,
    )
    r = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok),
        json={"price_id": p["id"], "units": 2},
    )
    oid = r.json()["id"]

    r = await client.post(
        f"/api/v1/marketplace/orders/{oid}/pay", headers=_h(tok),
        json={"external_ref": "ALIPAY-DEMO-001"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paid"
    assert body["external_ref"] == "ALIPAY-DEMO-001"
    assert body["activated_at"] is not None
    # 2 units × 30 days = 60 days expiry.
    assert body["expires_at"] is not None


async def test_cannot_pay_twice(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(client, tok, lid)
    r = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok),
        json={"price_id": p["id"]},
    )
    oid = r.json()["id"]
    await client.post(
        f"/api/v1/marketplace/orders/{oid}/pay", headers=_h(tok),
    )
    r = await client.post(
        f"/api/v1/marketplace/orders/{oid}/pay", headers=_h(tok),
    )
    assert r.status_code == 400


async def test_cancel_then_refund_flow(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(client, tok, lid)

    # Create pending -> cancel -> cannot refund cancelled.
    r = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok),
        json={"price_id": p["id"]},
    )
    oid = r.json()["id"]
    r = await client.post(
        f"/api/v1/marketplace/orders/{oid}/cancel", headers=_h(tok),
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled"

    r = await client.post(
        f"/api/v1/marketplace/orders/{oid}/refund", headers=_h(tok),
    )
    assert r.status_code == 400

    # New order, pay, then refund.
    r = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok),
        json={"price_id": p["id"]},
    )
    oid2 = r.json()["id"]
    await client.post(
        f"/api/v1/marketplace/orders/{oid2}/pay", headers=_h(tok),
    )
    r = await client.post(
        f"/api/v1/marketplace/orders/{oid2}/refund", headers=_h(tok),
    )
    assert r.status_code == 200 and r.json()["status"] == "refunded"


async def test_cross_org_order_isolation(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(client, tok_a, lid)

    r = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok_a),
        json={"price_id": p["id"]},
    )
    oid = r.json()["id"]

    # B cannot see A's order.
    r = await client.get(
        f"/api/v1/marketplace/orders/{oid}", headers=_h(tok_b),
    )
    assert r.status_code == 404

    r = await client.get(
        "/api/v1/marketplace/orders", headers=_h(tok_b),
    )
    assert r.json() == []


async def test_revenue_by_listing_only_counts_paid(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(
        client, tok, lid,
        unit_price_cny_cents=10000, platform_fee_bps=1500,
    )

    # 3 orders: 1 paid, 1 pending, 1 cancelled.
    ids = []
    for _ in range(3):
        r = await client.post(
            "/api/v1/marketplace/orders", headers=_h(tok),
            json={"price_id": p["id"]},
        )
        ids.append(r.json()["id"])
    await client.post(
        f"/api/v1/marketplace/orders/{ids[0]}/pay", headers=_h(tok),
    )
    await client.post(
        f"/api/v1/marketplace/orders/{ids[2]}/cancel", headers=_h(tok),
    )

    r = await client.get(
        f"/api/v1/marketplace/listings/{lid}/revenue", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["paid_orders"] == 1
    assert body["gross_cny_cents"] == 10000
    assert body["platform_fee_cny_cents"] == 1500
    assert body["vendor_payout_cny_cents"] == 8500


async def test_list_orders_status_filter(client) -> None:
    tok, _, _ = await _mkuser()
    lid = uuid4()
    p = await _mkprice(client, tok, lid)
    r1 = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok),
        json={"price_id": p["id"]},
    )
    r2 = await client.post(
        "/api/v1/marketplace/orders", headers=_h(tok),
        json={"price_id": p["id"]},
    )
    await client.post(
        f"/api/v1/marketplace/orders/{r1.json()['id']}/pay",
        headers=_h(tok),
    )

    r = await client.get(
        "/api/v1/marketplace/orders?status_=paid", headers=_h(tok),
    )
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == r1.json()["id"]

    r = await client.get(
        "/api/v1/marketplace/orders?status_=pending", headers=_h(tok),
    )
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == r2.json()["id"]
