"""Tests for R17 Flight Approval state machine + authority routing."""
from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    from app.services import rate_limit
    rate_limit.reset_bucket()
    yield
    rate_limit.reset_bucket()


async def _login(client, email="approval@example.com", pw="StrongPassW0rd#"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=uuid4(),
            email=email,
            hashed_pw=hash_password(pw),
            role="operator",
        ))
        await s.commit()

    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": pw}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_authority_catalog(client):
    r = await client.get("/api/v1/approvals/authorities/catalog")
    assert r.status_code == 200
    codes = {a["code"] for a in r.json()["authorities"]}
    assert {"uom", "local_police", "atc", "market_regulator"} <= codes


@pytest.mark.asyncio
async def test_authority_routing_nanning_high_alt(client):
    tok = await _login(client, "route@example.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    # Nanning bbox polygon @ >120m altitude → uom + local_police + atc
    now = datetime.now(tz=timezone.utc)
    body = {
        "title": "南宁市巡线飞行",
        "purpose": "输电线路巡检",
        "category": "routine",
        "area_polygon": [
            [108.30, 22.70], [108.35, 22.70],
            [108.35, 22.75], [108.30, 22.75],
        ],
        "max_alt_m": 150.0,
        "start_ts": now.isoformat(),
        "end_ts": (now + timedelta(hours=2)).isoformat(),
    }
    r = await client.post("/api/v1/approvals", json=body, headers=hdrs)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    r = await client.post(
        f"/api/v1/approvals/{aid}/route?aircraft_weight_kg=8.0",
        headers=hdrs,
    )
    assert r.status_code == 200
    codes = [a["code"] for a in r.json()["authorities"]]
    assert "uom" in codes
    assert "local_police" in codes  # Nanning bbox hit
    assert "atc" in codes           # >120m gate
    assert "market_regulator" not in codes  # 8kg < 15kg


@pytest.mark.asyncio
async def test_heavy_aircraft_routes_market_regulator(client):
    tok = await _login(client, "heavy@example.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "20kg 大型机测试",
            "max_alt_m": 90.0,
            "area_polygon": [[110.0, 30.0], [110.1, 30.0], [110.1, 30.1], [110.0, 30.1]],
        },
        headers=hdrs,
    )
    aid = r.json()["id"]
    r = await client.post(
        f"/api/v1/approvals/{aid}/route?aircraft_weight_kg=20.0",
        headers=hdrs,
    )
    codes = [a["code"] for a in r.json()["authorities"]]
    assert "market_regulator" in codes


@pytest.mark.asyncio
async def test_full_state_machine_flow(client):
    tok = await _login(client, "flow@example.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    now = datetime.now(tz=timezone.utc)

    # 1. Draft.
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "全流程测试",
            "purpose": "航拍",
            "pilot_license": "PILOT-2026-001",
            "aircraft_reg": "UAS-CN-0001",
            "insurance_no": "PICC-2026-99",
            "area_polygon": [
                [108.30, 22.70], [108.303, 22.70],
                [108.303, 22.703], [108.30, 22.703],
            ],
            "max_alt_m": 100.0,
            "start_ts": (now - timedelta(minutes=5)).isoformat(),
            "end_ts": (now + timedelta(hours=1)).isoformat(),
        },
        headers=hdrs,
    )
    aid = r.json()["id"]
    assert r.json()["status"] == "draft"

    # 2. Submit → in_review with 2 authorities (uom + local_police).
    r = await client.post(
        f"/api/v1/approvals/{aid}/submit?aircraft_weight_kg=5.0",
        headers=hdrs,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "in_review"
    codes = {a["authority_code"] for a in body["authorities"]}
    assert "uom" in codes and "local_police" in codes

    # 3. Each authority approves.
    for code in codes:
        r = await client.post(
            f"/api/v1/approvals/{aid}/authorities/{code}/decide",
            json={"decision": "approved", "external_ref": f"{code}-REF-001"},
            headers=hdrs,
        )
        assert r.status_code == 200

    r = await client.get(f"/api/v1/approvals/{aid}", headers=hdrs)
    assert r.json()["status"] == "approved"

    # 4. Preflight — should pass all fails.
    r = await client.post(
        f"/api/v1/approvals/{aid}/preflight-check",
        json={"remote_id_broadcast": True, "intended_max_alt_m": 80.0},
        headers=hdrs,
    )
    assert r.status_code == 200
    result = r.json()
    assert result["ok"] is True, result
    assert result["blocking"] is False

    # 5. Mark flown.
    r = await client.post(f"/api/v1/approvals/{aid}/mark-flown", headers=hdrs)
    assert r.json()["status"] == "flown"


@pytest.mark.asyncio
async def test_rejection_flow(client):
    tok = await _login(client, "reject@example.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "被驳回测试",
            "area_polygon": [[108.30, 22.70], [108.35, 22.75]],
            "max_alt_m": 100.0,
        },
        headers=hdrs,
    )
    aid = r.json()["id"]
    await client.post(f"/api/v1/approvals/{aid}/submit", headers=hdrs)
    r = await client.post(
        f"/api/v1/approvals/{aid}/authorities/uom/decide",
        json={"decision": "rejected", "reason": "空域冲突"},
        headers=hdrs,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["reject_reason"] == "空域冲突"


@pytest.mark.asyncio
async def test_preflight_blocks_missing_fields(client):
    tok = await _login(client, "preflight_fail@example.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/approvals",
        json={"title": "缺字段测试"},
        headers=hdrs,
    )
    aid = r.json()["id"]
    r = await client.post(
        f"/api/v1/approvals/{aid}/preflight-check",
        json={"remote_id_broadcast": False},
        headers=hdrs,
    )
    result = r.json()
    assert result["blocking"] is True
    keys = {i["key"] for i in result["items"] if i["severity"] == "fail"}
    # At minimum: status not approved + missing pilot_license + missing aircraft_reg + remote_id off
    assert "approval_status" in keys
    assert "pilot_license" in keys
    assert "aircraft_reg" in keys
    assert "remote_id" in keys


@pytest.mark.asyncio
async def test_cannot_edit_after_submit(client):
    tok = await _login(client, "editafter@example.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "编辑锁定测试",
            "area_polygon": [[108.30, 22.70], [108.35, 22.75]],
            "max_alt_m": 100.0,
        },
        headers=hdrs,
    )
    aid = r.json()["id"]
    await client.post(f"/api/v1/approvals/{aid}/submit", headers=hdrs)
    r = await client.patch(
        f"/api/v1/approvals/{aid}",
        json={"title": "改标题"},
        headers=hdrs,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_cancel_flow(client):
    tok = await _login(client, "cancel@example.com")
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "取消测试",
            "area_polygon": [[108.30, 22.70], [108.35, 22.75]],
            "max_alt_m": 100.0,
        },
        headers=hdrs,
    )
    aid = r.json()["id"]
    r = await client.post(f"/api/v1/approvals/{aid}/cancel", headers=hdrs)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
