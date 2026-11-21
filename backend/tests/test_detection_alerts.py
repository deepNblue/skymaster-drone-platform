"""E3.3 · Detection alert rule tests — CRUD + matching + REST."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.detection_alert_rule import DetectionAlertRule
from app.models.user import User
from app.models.vision_copilot import VisionDetection
from app.services.auth import create_access_token, hash_password
from app.services.detection_alert import rule_matches_cluster

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"al+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid, org


# =========== Pure matching ==============

def _rule(**kw):
    return DetectionAlertRule(
        id=uuid4(), org_id=uuid4(),
        name=kw.get("name", "r1"),
        label=kw.get("label", "person"),
        min_member_count=kw.get("min_member_count", 3),
        min_peak_confidence=kw.get("min_peak_confidence", 0.0),
        action=kw.get("action", "log"),
        cooldown_seconds=kw.get("cooldown_seconds", 300),
        enabled=kw.get("enabled", True),
        last_fired_at=kw.get("last_fired_at"),
    )


def test_matches_basic() -> None:
    r = _rule(label="person", min_member_count=3)
    c = {"label": "person", "member_count": 5, "peak_confidence": 0.9}
    assert rule_matches_cluster(r, c) is True


def test_matches_wildcard_label() -> None:
    r = _rule(label="*", min_member_count=1)
    c = {"label": "anything", "member_count": 2, "peak_confidence": 0.5}
    assert rule_matches_cluster(r, c) is True


def test_no_match_label_mismatch() -> None:
    r = _rule(label="person", min_member_count=1)
    c = {"label": "vehicle", "member_count": 5, "peak_confidence": 0.9}
    assert rule_matches_cluster(r, c) is False


def test_no_match_below_member_count() -> None:
    r = _rule(min_member_count=10)
    c = {"label": "person", "member_count": 3, "peak_confidence": 0.9}
    assert rule_matches_cluster(r, c) is False


def test_no_match_below_peak_conf() -> None:
    r = _rule(min_peak_confidence=0.95)
    c = {"label": "person", "member_count": 100, "peak_confidence": 0.8}
    assert rule_matches_cluster(r, c) is False


def test_no_match_disabled() -> None:
    r = _rule(enabled=False)
    c = {"label": "person", "member_count": 100, "peak_confidence": 1.0}
    assert rule_matches_cluster(r, c) is False


def test_no_match_in_cooldown() -> None:
    now = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)
    r = _rule(
        cooldown_seconds=300,
        last_fired_at=now - timedelta(seconds=120),  # 2min ago
    )
    c = {"label": "person", "member_count": 5, "peak_confidence": 0.9}
    assert rule_matches_cluster(r, c, now=now) is False


def test_match_after_cooldown() -> None:
    now = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)
    r = _rule(
        cooldown_seconds=300,
        last_fired_at=now - timedelta(seconds=400),
    )
    c = {"label": "person", "member_count": 5, "peak_confidence": 0.9}
    assert rule_matches_cluster(r, c, now=now) is True


# =========== REST CRUD ==============

async def test_crud_flow(client) -> None:
    tok, _, _ = await _mkuser()
    # Create
    r = await client.post(
        "/api/v1/vision/alerts", headers=_h(tok),
        json={
            "name": "拥堵告警", "label": "person",
            "min_member_count": 5, "action": "feishu",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    rid = body["id"]
    assert body["label"] == "person"
    assert body["action"] == "feishu"
    assert body["enabled"] is True

    # Get
    r = await client.get(
        f"/api/v1/vision/alerts/{rid}", headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["min_member_count"] == 5

    # List
    r = await client.get(
        "/api/v1/vision/alerts", headers=_h(tok),
    )
    assert len(r.json()) == 1

    # Update
    r = await client.patch(
        f"/api/v1/vision/alerts/{rid}", headers=_h(tok),
        json={"min_member_count": 10, "enabled": False},
    )
    assert r.status_code == 200
    assert r.json()["min_member_count"] == 10
    assert r.json()["enabled"] is False

    # enabled_only filter should hide it now
    r = await client.get(
        "/api/v1/vision/alerts?enabled_only=true", headers=_h(tok),
    )
    assert r.json() == []

    # Delete
    r = await client.delete(
        f"/api/v1/vision/alerts/{rid}", headers=_h(tok),
    )
    assert r.status_code == 204

    r = await client.get(
        f"/api/v1/vision/alerts/{rid}", headers=_h(tok),
    )
    assert r.status_code == 404


async def test_create_invalid_action(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/vision/alerts", headers=_h(tok),
        json={
            "name": "r", "label": "person",
            "action": "smoke_signal",
        },
    )
    assert r.status_code == 400


async def test_org_isolation(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/vision/alerts", headers=_h(tok_a),
        json={"name": "own", "label": "person", "action": "log"},
    )
    rid = r.json()["id"]
    # B cannot see A's rule
    r = await client.get(
        f"/api/v1/vision/alerts/{rid}", headers=_h(tok_b),
    )
    assert r.status_code == 404
    # B's list is empty
    r = await client.get(
        "/api/v1/vision/alerts", headers=_h(tok_b),
    )
    assert r.json() == []


async def test_evaluate_fires(client) -> None:
    tok, _, org = await _mkuser()
    # Create rule
    await client.post(
        "/api/v1/vision/alerts", headers=_h(tok),
        json={
            "name": "person聚集", "label": "person",
            "min_member_count": 3, "action": "log",
            "cooldown_seconds": 60,
        },
    )
    # Seed 4 person detections at same spot
    now = datetime.now(timezone.utc)
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        for i in range(4):
            s.add(VisionDetection(
                tenant_id=org, label="person",
                confidence=0.9, lat=30.6, lng=104.0,
                created_at=now - timedelta(seconds=10 - i),
            ))
        await s.commit()
    # Evaluate
    r = await client.post(
        "/api/v1/vision/alerts/evaluate?since_seconds=60",
        headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fire_count"] == 1
    fire = body["fires"][0]
    assert fire["label"] == "person"
    assert fire["member_count"] == 4
    assert fire["rule_name"] == "person聚集"

    # Second call within cooldown → 0 fires
    r = await client.post(
        "/api/v1/vision/alerts/evaluate?since_seconds=60",
        headers=_h(tok),
    )
    assert r.json()["fire_count"] == 0


async def test_evaluate_no_matching_clusters(client) -> None:
    tok, _, org = await _mkuser()
    await client.post(
        "/api/v1/vision/alerts", headers=_h(tok),
        json={
            "name": "vehicle 高置信", "label": "vehicle",
            "min_member_count": 3, "min_peak_confidence": 0.95,
            "action": "log",
        },
    )
    now = datetime.now(timezone.utc)
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        # Below peak_conf threshold
        for i in range(5):
            s.add(VisionDetection(
                tenant_id=org, label="vehicle",
                confidence=0.6, lat=30.6, lng=104.0,
                created_at=now - timedelta(seconds=10 - i),
            ))
        await s.commit()
    r = await client.post(
        "/api/v1/vision/alerts/evaluate?since_seconds=60",
        headers=_h(tok),
    )
    assert r.json()["fire_count"] == 0
