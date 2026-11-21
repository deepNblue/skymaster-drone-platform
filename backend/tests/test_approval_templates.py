"""E2.5 · Flight approval template API tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
            id=uid, email=f"at+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=org, role="user")
    return tok, uid, org


VALID_PAYLOAD = {
    "name": "巡线-乡道",
    "category": "routine",
    "purpose": "农村配电线路巡检",
    "pilot_name": "张三",
    "pilot_license": "CAAC-000123",
    "aircraft_reg": "UAV-0001",
    "max_alt_m": 120.0,
    "min_alt_m": 30.0,
    "authorities_preset": [
        {"code": "uom", "name": "民航局 UOM", "channel": "api", "priority": 1},
        {"code": "local_police", "name": "属地公安", "channel": "manual", "priority": 2},
    ],
    "checklist_json": [
        {"id": "batt", "text": "电池充满 ≥ 90%"},
        {"id": "gps", "text": "GPS 卫星数 ≥ 10"},
    ],
}


async def test_create_list_get_update_delete(client) -> None:
    tok, _, _ = await _mkuser()

    r = await client.post(
        "/api/v1/approval-templates", headers=_h(tok), json=VALID_PAYLOAD,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    tid = body["id"]
    assert body["name"] == "巡线-乡道"
    assert body["apply_count"] == 0
    assert len(body["authorities_preset"]) == 2

    # List
    r = await client.get("/api/v1/approval-templates", headers=_h(tok))
    assert r.status_code == 200
    assert any(t["id"] == tid for t in r.json())

    # Get
    r = await client.get(
        f"/api/v1/approval-templates/{tid}", headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["pilot_license"] == "CAAC-000123"

    # Update
    r = await client.patch(
        f"/api/v1/approval-templates/{tid}",
        headers=_h(tok),
        json={"pilot_name": "李四", "max_alt_m": 100.0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["pilot_name"] == "李四"
    assert r.json()["max_alt_m"] == 100.0

    # Delete
    r = await client.delete(
        f"/api/v1/approval-templates/{tid}", headers=_h(tok),
    )
    assert r.status_code == 204

    r = await client.get(
        f"/api/v1/approval-templates/{tid}", headers=_h(tok),
    )
    assert r.status_code == 404


async def test_invalid_category_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/approval-templates",
        headers=_h(tok),
        json={**VALID_PAYLOAD, "category": "not-a-real-category"},
    )
    assert r.status_code == 400
    assert "category" in r.text.lower()


async def test_duplicate_name_within_org_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    r1 = await client.post(
        "/api/v1/approval-templates", headers=_h(tok), json=VALID_PAYLOAD,
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/approval-templates", headers=_h(tok), json=VALID_PAYLOAD,
    )
    assert r2.status_code == 400
    assert "already exists" in r2.text.lower()


async def test_authorities_preset_missing_fields_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    bad = dict(VALID_PAYLOAD)
    bad["authorities_preset"] = [{"code": "uom"}]  # missing "name"
    r = await client.post(
        "/api/v1/approval-templates", headers=_h(tok), json=bad,
    )
    assert r.status_code == 400


async def test_apply_creates_flight_approval(client) -> None:
    tok, uid, _ = await _mkuser()

    # Create template
    r = await client.post(
        "/api/v1/approval-templates", headers=_h(tok), json=VALID_PAYLOAD,
    )
    tid = r.json()["id"]

    now = datetime.now(timezone.utc)
    r = await client.post(
        f"/api/v1/approval-templates/{tid}/apply",
        headers=_h(tok),
        json={
            "title": "2026-07-16 巡线飞行",
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
            "area_polygon_override": [[103.0, 30.5], [103.1, 30.5], [103.1, 30.6]],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert UUID(body["approval_id"])
    assert body["status"] == "draft"

    # Template's apply_count bumped
    r = await client.get(
        f"/api/v1/approval-templates/{tid}", headers=_h(tok),
    )
    assert r.json()["apply_count"] == 1


async def test_apply_start_after_end_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/approval-templates", headers=_h(tok), json=VALID_PAYLOAD,
    )
    tid = r.json()["id"]
    now = datetime.now(timezone.utc)
    r = await client.post(
        f"/api/v1/approval-templates/{tid}/apply",
        headers=_h(tok),
        json={
            "title": "bad-time",
            "start_ts": (now + timedelta(hours=2)).isoformat(),
            "end_ts": now.isoformat(),
        },
    )
    assert r.status_code == 400
    assert "start_ts" in r.text.lower()


async def test_apply_missing_template_404(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc)
    r = await client.post(
        f"/api/v1/approval-templates/{uuid4()}/apply",
        headers=_h(tok),
        json={
            "title": "x",
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 404


async def test_cross_org_get_returns_404(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()

    r = await client.post(
        "/api/v1/approval-templates", headers=_h(tok_a), json=VALID_PAYLOAD,
    )
    tid = r.json()["id"]

    r = await client.get(
        f"/api/v1/approval-templates/{tid}", headers=_h(tok_b),
    )
    assert r.status_code == 404


async def test_list_filter_by_category(client) -> None:
    tok, _, _ = await _mkuser()
    await client.post(
        "/api/v1/approval-templates", headers=_h(tok),
        json={**VALID_PAYLOAD, "name": "t-routine", "category": "routine"},
    )
    await client.post(
        "/api/v1/approval-templates", headers=_h(tok),
        json={**VALID_PAYLOAD, "name": "t-night", "category": "night"},
    )
    r = await client.get(
        "/api/v1/approval-templates?category=night", headers=_h(tok),
    )
    names = [t["name"] for t in r.json()]
    assert "t-night" in names
    assert "t-routine" not in names
