"""Tests for R21 Step E — Approval-as-a-Service."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    from app.services import rate_limit
    rate_limit.reset_bucket()
    yield
    rate_limit.reset_bucket()


# ---------------------------------------------------------------------------
# Pure crypto helpers
# ---------------------------------------------------------------------------


def test_sign_and_verify_signature_roundtrip():
    from app.services.aaas import sign_payload, verify_signature
    secret = "s" * 40
    ts = "2026-07-10T12:00:00+00:00"
    body = b'{"hello": "world"}'
    sig = sign_payload(secret, ts, body)
    assert len(sig) == 64  # sha256 hex
    assert verify_signature(secret, ts, body, sig) is True
    # any tamper breaks it
    assert verify_signature(secret, ts, body + b"x", sig) is False
    assert verify_signature("other", ts, body, sig) is False


def test_new_client_secret_length():
    from app.services.aaas import new_client_secret
    s1 = new_client_secret()
    s2 = new_client_secret()
    assert len(s1) >= 30
    assert s1 != s2  # random


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def test_build_approval_event_shape():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.services.aaas import build_approval_event
    from uuid import UUID as U

    ap = SimpleNamespace(
        id=U("11111111-1111-1111-1111-111111111111"),
        title="test",
        category="routine",
        status="submitted",
        start_ts=datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc),
        end_ts=datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc),
        aircraft_reg="ABC-01",
        pilot_name="张三",
        pilot_license="UAV-001",
        region="CD-JN",
        mission_id=None,
    )
    p = build_approval_event("approval.submitted", ap)
    assert p["event"] == "approval.submitted"
    assert "event_id" in p and "sent_at" in p
    assert p["approval"]["title"] == "test"
    assert p["approval"]["planned_start"] == "2026-07-10T08:00:00+00:00"
    # JSON-serialisable
    assert json.loads(json.dumps(p))


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


async def _make_user(client, email: str, role: str = "admin") -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=uuid4(), email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role,
        ))
        await s.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassW0rd#"},
    )
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_non_admin_forbidden(client):
    tok = await _make_user(client, "aaas_viewer@x.com", role="viewer")
    r = await client.get(
        "/api/v1/aaas/clients",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_event_catalog(client):
    """Catalog is available to any authenticated user (dropdown for admin UI)."""
    tok = await _make_user(client, "aaas_cat@x.com", role="admin")
    r = await client.get(
        "/api/v1/aaas/events/catalog",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert "approval.submitted" in r.json()["events"]
    assert "approval.rejected" in r.json()["events"]


@pytest.mark.asyncio
async def test_create_client_generates_secret_and_lists(client):
    tok = await _make_user(client, "aaas_admin@x.com", role="admin")
    h = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        "/api/v1/aaas/clients",
        json={
            "name": "省公安厅UOM",
            "description": "公安空管系统",
            "callback_url": "https://example.gov.cn/webhook/uav",
            "events": ["approval.approved", "approval.rejected"],
            "active": True,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "省公安厅UOM"
    assert len(body["secret"]) >= 30
    cid = body["id"]

    r = await client.get("/api/v1/aaas/clients", headers=h)
    assert r.status_code == 200
    assert any(c["id"] == cid for c in r.json())


@pytest.mark.asyncio
async def test_create_client_rejects_unknown_event(client):
    tok = await _make_user(client, "aaas_evtbad@x.com", role="admin")
    r = await client.post(
        "/api/v1/aaas/clients",
        json={
            "name": "bad",
            "callback_url": "https://x.com/hook",
            "events": ["approval.moon_landing"],
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 400
    assert "unknown events" in r.json()["detail"]


@pytest.mark.asyncio
async def test_rotate_secret_returns_new_value(client):
    tok = await _make_user(client, "aaas_rot@x.com", role="admin")
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/aaas/clients",
        json={
            "name": "svc",
            "callback_url": "https://x.com/hook",
        },
        headers=h,
    )
    cid = r.json()["id"]
    old = r.json()["secret"]

    r = await client.post(
        f"/api/v1/aaas/clients/{cid}/rotate-secret",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["secret"] != old


# ---------------------------------------------------------------------------
# Fan-out — stub deliver_event to avoid real HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_calls_deliver_for_matching_subscribers(client, monkeypatch):
    """Create two subscribers (one filtered, one wildcard), fire an event,
    verify only matching subscribers get an HTTP attempt."""
    tok = await _make_user(client, "aaas_fan@x.com", role="admin")
    h = {"Authorization": f"Bearer {tok}"}

    # Subscriber #1 — subscribes only to approval.submitted.
    r = await client.post(
        "/api/v1/aaas/clients",
        json={
            "name": "sub_only",
            "callback_url": "http://127.0.0.1:1/hook",
            "events": ["approval.submitted"],
        },
        headers=h,
    )
    assert r.status_code == 201
    cid1 = r.json()["id"]

    # Subscriber #2 — wildcard.
    r = await client.post(
        "/api/v1/aaas/clients",
        json={
            "name": "all_events",
            "callback_url": "http://127.0.0.1:1/hook",
            "events": None,
        },
        headers=h,
    )
    assert r.status_code == 201
    cid2 = r.json()["id"]

    # Stub the real HTTP call so tests don't hit network.
    delivered: list[dict] = []

    async def _fake_deliver(**kw):
        delivered.append(kw)
        return (200, "OK", "sig")

    from app.services import aaas as aaas_svc
    monkeypatch.setattr(aaas_svc, "deliver_event", _fake_deliver)

    # Create + submit an approval via existing approvals API.
    from datetime import datetime, timedelta, timezone
    start = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "AaaS 触发测试",
            "category": "routine",
            "start_ts": start.isoformat(),
            "end_ts": end.isoformat(),
            "aircraft_reg": "TEST-01",
            "pilot_name": "张三",
            "pilot_license": "UAV-001",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    ap_id = r.json()["id"]

    r = await client.post(f"/api/v1/approvals/{ap_id}/submit", headers=h)
    assert r.status_code == 200, r.text

    # Both subscribers should have been called (both match submitted).
    assert len(delivered) == 2
    for call in delivered:
        assert call["event"] == "approval.submitted"
        assert "url" in call


@pytest.mark.asyncio
async def test_fanout_records_delivery_and_status(client, monkeypatch):
    tok = await _make_user(client, "aaas_rec@x.com", role="admin")
    h = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        "/api/v1/aaas/clients",
        json={
            "name": "rec_test",
            "callback_url": "http://127.0.0.1:1/hook",
        },
        headers=h,
    )
    cid = r.json()["id"]

    from app.services import aaas as aaas_svc

    # Fail once (network-style), so a retry row is recorded.
    async def _fake_deliver(**kw):
        return (500, "boom", "sig")
    monkeypatch.setattr(aaas_svc, "deliver_event", _fake_deliver)

    # Fire a test event without needing a real approval:
    from datetime import datetime, timedelta, timezone
    start = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "fan test",
            "category": "routine",
            "start_ts": start.isoformat(),
            "end_ts": end.isoformat(),
            "aircraft_reg": "TEST-02",
            "pilot_name": "李四",
            "pilot_license": "UAV-002",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    ap_id = r.json()["id"]
    await client.post(f"/api/v1/approvals/{ap_id}/submit", headers=h)

    # List deliveries — should have a 'retrying' row.
    r = await client.get(
        f"/api/v1/aaas/deliveries?client_id={cid}",
        headers=h,
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert rows[0]["status"] == "retrying"
    assert rows[0]["last_status_code"] == 500
    assert rows[0]["attempts"] == 1


@pytest.mark.asyncio
async def test_test_fire_replays_event(client, monkeypatch):
    """POST /aaas/test-fire re-sends an event so admins can verify a
    subscriber's endpoint end-to-end."""
    tok = await _make_user(client, "aaas_tf@x.com", role="admin")
    h = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        "/api/v1/aaas/clients",
        json={
            "name": "tf",
            "callback_url": "http://127.0.0.1:1/hook",
        },
        headers=h,
    )
    cid = r.json()["id"]

    # Make an approval to reference.
    from datetime import datetime, timedelta, timezone
    start = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "tf ap",
            "category": "routine",
            "start_ts": start.isoformat(),
            "end_ts": end.isoformat(),
            "aircraft_reg": "TF-01",
            "pilot_name": "王五",
            "pilot_license": "UAV-003",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    ap_id = r.json()["id"]

    calls: list[str] = []
    from app.services import aaas as aaas_svc

    async def _fake_deliver(**kw):
        calls.append(kw["event"])
        return (204, "", "sig")
    monkeypatch.setattr(aaas_svc, "deliver_event", _fake_deliver)

    r = await client.post(
        f"/api/v1/aaas/test-fire/{ap_id}?event=approval.approved",
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["delivered_to"] == 1
    assert calls == ["approval.approved"]


@pytest.mark.asyncio
async def test_test_fire_rejects_unknown_event(client):
    tok = await _make_user(client, "aaas_tfb@x.com", role="admin")
    r = await client.post(
        f"/api/v1/aaas/test-fire/{uuid4()}?event=approval.moon_landing",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_stats_endpoint(client):
    tok = await _make_user(client, "aaas_stat@x.com", role="admin")
    r = await client.get(
        "/api/v1/aaas/stats",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert "by_status" in r.json()
