"""E2.5c · Airspace conflict gate integration into /submit.

Verifies that /approvals/{id}/submit consults the airspace_calendar
service, rejects with HTTP 409 when a conflict exists, honours the
?force=true bypass, and reserves the airspace after successful submit.
"""
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
            id=uid, email=f"asgate+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=org, role="user")
    return tok, uid, org


# Small ~5m x 5m patch (~5e-5 deg) — well below the 1 km² high-risk
# trigger threshold in approval_router.is_high_risk, so we exercise
# the airspace-conflict gate rather than the high-risk gate.
POLY = [
    [103.00000, 30.50000], [103.00005, 30.50000],
    [103.00005, 30.50005], [103.00000, 30.50005],
]


async def _mkapproval(
    client, tok: str, start: datetime, end: datetime,
) -> str:
    r = await client.post(
        "/api/v1/approvals", headers=_h(tok),
        json={
            "title": "T7.5-gate",
            "purpose": "线路巡检",
            "area_polygon": POLY,
            "start_ts": start.isoformat(),
            "end_ts": end.isoformat(),
            "min_alt_m": 30.0,
            "max_alt_m": 120.0,
            "category": "routine",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_submit_blocked_by_uom_conflict(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # Existing UOM slot 08:00-10:00 same polygon.
    r = await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "uom",
            "external_ref": "UOM-CONFLICT-01",
            "title": "existing UOM slot",
            "geo_polygon": POLY,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
            "min_alt_m": 20.0, "max_alt_m": 200.0,
        },
    )
    assert r.status_code == 201, r.text

    aid = await _mkapproval(
        client, tok,
        start=(now + timedelta(hours=1)),
        end=(now + timedelta(hours=3)),
    )
    r = await client.post(
        f"/api/v1/approvals/{aid}/submit", headers=_h(tok),
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["detail"] == "airspace_conflict"
    assert detail["count"] == 1
    assert detail["conflicts"][0]["source"] == "uom"
    assert detail["conflicts"][0]["external_ref"] == "UOM-CONFLICT-01"


async def test_submit_force_bypasses_conflict(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "uom", "title": "existing",
            "geo_polygon": POLY,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    aid = await _mkapproval(
        client, tok,
        start=(now + timedelta(hours=1)),
        end=(now + timedelta(hours=3)),
    )
    r = await client.post(
        f"/api/v1/approvals/{aid}/submit?force=true", headers=_h(tok),
    )
    # With force=true we skip the gate; downstream status either
    # in_review or pending_second_approval (high-risk) is fine.
    assert r.status_code == 200, r.text
    assert r.json()["status"] in {
        "in_review", "submitted", "pending_second_approval",
    }


async def test_submit_no_conflict_passes_and_reserves_slot(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    aid = await _mkapproval(
        client, tok,
        start=(now + timedelta(hours=5)),
        end=(now + timedelta(hours=6)),
    )
    r = await client.post(
        f"/api/v1/approvals/{aid}/submit", headers=_h(tok),
    )
    assert r.status_code == 200, r.text

    # After submit, a calendar entry with approval_id=aid should exist.
    r = await client.get(
        "/api/v1/airspace-calendar", headers=_h(tok),
    )
    assert r.status_code == 200
    matches = [e for e in r.json() if e.get("approval_id") == aid]
    assert len(matches) == 1
    assert matches[0]["source"] == "local"


async def test_second_submit_after_first_reserved_blocks(client) -> None:
    """Second approval overlapping the first (now-reserved) slot must fail."""
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # First submit: OK, reserves the slot.
    aid1 = await _mkapproval(
        client, tok,
        start=(now + timedelta(hours=10)),
        end=(now + timedelta(hours=11)),
    )
    r = await client.post(
        f"/api/v1/approvals/{aid1}/submit", headers=_h(tok),
    )
    assert r.status_code == 200, r.text

    # Second submit overlaps first — should now 409.
    aid2 = await _mkapproval(
        client, tok,
        start=(now + timedelta(hours=10, minutes=30)),
        end=(now + timedelta(hours=11, minutes=30)),
    )
    r = await client.post(
        f"/api/v1/approvals/{aid2}/submit", headers=_h(tok),
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["detail"] == "airspace_conflict"
    assert detail["conflicts"][0]["source"] == "local"


async def test_no_conflict_when_time_window_disjoint(client) -> None:
    tok, _, _ = await _mkuser()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # Existing slot 08-10.
    await client.post(
        "/api/v1/airspace-calendar", headers=_h(tok),
        json={
            "source": "uom", "title": "past",
            "geo_polygon": POLY,
            "start_ts": now.isoformat(),
            "end_ts": (now + timedelta(hours=2)).isoformat(),
        },
    )
    # New approval 12-13 — disjoint.
    aid = await _mkapproval(
        client, tok,
        start=(now + timedelta(hours=4)),
        end=(now + timedelta(hours=5)),
    )
    r = await client.post(
        f"/api/v1/approvals/{aid}/submit", headers=_h(tok),
    )
    assert r.status_code == 200, r.text
