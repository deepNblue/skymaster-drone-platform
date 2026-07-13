"""Tests for T5.0 Vision AI tools in Copilot v2 registry."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.drone import Drone
from app.models.vision_copilot import VisionDetection
from app.services.tool_registry import (
    DetectionStatsArgs,
    ListDetectionsArgs,
    ToolContext,
    detection_stats,
    list_detections,
    build_default_registry,
)


async def _seed(session, org_id, drone_id, samples):
    """Bulk insert VisionDetection rows.

    samples: list of tuples (label, confidence, minutes_ago)
    """
    now = datetime.now(timezone.utc)
    for label, conf, mins_ago in samples:
        session.add(
            VisionDetection(
                id=uuid4(),
                tenant_id=org_id,
                drone_id=drone_id,
                label=label,
                confidence=conf,
                bbox=[0.1, 0.1, 0.3, 0.3],
                created_at=now - timedelta(minutes=mins_ago),
                model_tag="yolov8n",
                runtime="onnx",
                status="new",
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_list_detections_basic(client):
    """No filters → returns all detections for the org, newest first.
    Also verifies that lat/lng/alt_m are surfaced in the payload."""
    from app.db import engine
    Session = async_sessionmaker(engine, expire_on_commit=False)
    org_id = uuid4()
    drone_id = uuid4()
    async with Session() as db:
        db.add(Drone(
            id=drone_id, org_id=org_id, sn=f"SN-{uuid4().hex[:8]}",
            model="X", protocol="mavlink", status="online",
        ))
        # Seed manually (not via _seed helper) so we can attach lat/lng.
        now = datetime.now(timezone.utc)
        db.add_all([
            VisionDetection(
                id=uuid4(), tenant_id=org_id, drone_id=drone_id,
                label="person", confidence=0.92,
                bbox=[0.1, 0.1, 0.3, 0.3],
                lat=30.6720, lng=104.0655, alt_m=120.0,
                created_at=now - timedelta(minutes=1),
                model_tag="yolov8n", runtime="onnx", status="new",
            ),
            VisionDetection(
                id=uuid4(), tenant_id=org_id, drone_id=drone_id,
                label="vehicle", confidence=0.71,
                bbox=[0.4, 0.4, 0.6, 0.6],
                created_at=now - timedelta(minutes=5),
                model_tag="yolov8n", runtime="onnx", status="new",
            ),
            VisionDetection(
                id=uuid4(), tenant_id=org_id, drone_id=drone_id,
                label="person", confidence=0.55,
                bbox=[0.1, 0.1, 0.2, 0.2],
                created_at=now - timedelta(minutes=30),
                model_tag="yolov8n", runtime="onnx", status="new",
            ),
        ])
        await db.commit()

    async with Session() as db:
        ctx = ToolContext(db=db, org_id=org_id, user_id=uuid4())
        out = await list_detections(ctx, ListDetectionsArgs(limit=10))
    assert out["count"] == 3
    labels = [d["label"] for d in out["detections"]]
    assert labels == ["person", "vehicle", "person"]  # newest first
    top = out["detections"][0]
    assert top["model_tag"] == "yolov8n"
    # lat/lng/alt_m must be exposed to the LLM/UI so the operator can
    # click-to-focus on the map (T5.3).
    assert top["lat"] == pytest.approx(30.6720)
    assert top["lng"] == pytest.approx(104.0655)
    assert top["alt_m"] == pytest.approx(120.0)
    # Second detection has no coords → should be None (not KeyError).
    assert out["detections"][1]["lat"] is None
    assert out["detections"][1]["lng"] is None


@pytest.mark.asyncio
async def test_list_detections_filters(client):
    """label + min_confidence + since_minutes narrow the result set."""
    from app.db import engine
    Session = async_sessionmaker(engine, expire_on_commit=False)
    org_id = uuid4()
    drone_id = uuid4()
    async with Session() as db:
        db.add(Drone(
            id=drone_id, org_id=org_id, sn=f"SN-{uuid4().hex[:8]}",
            model="X", protocol="mavlink", status="online",
        ))
        await _seed(db, org_id, drone_id, [
            ("person", 0.92, 1),   # keep
            ("person", 0.30, 2),   # drop: below min_confidence
            ("person", 0.95, 200), # drop: outside window
            ("vehicle", 0.99, 1),  # drop: wrong label
        ])

    async with Session() as db:
        ctx = ToolContext(db=db, org_id=org_id, user_id=uuid4())
        out = await list_detections(ctx, ListDetectionsArgs(
            label="person", min_confidence=0.5, since_minutes=30, limit=10,
        ))
    assert out["count"] == 1
    assert out["detections"][0]["label"] == "person"
    assert out["detections"][0]["confidence"] >= 0.5


@pytest.mark.asyncio
async def test_list_detections_org_isolation(client):
    """A user in org A must NOT see detections seeded for org B."""
    from app.db import engine
    Session = async_sessionmaker(engine, expire_on_commit=False)
    org_a, org_b = uuid4(), uuid4()
    drone_a, drone_b = uuid4(), uuid4()
    async with Session() as db:
        db.add_all([
            Drone(id=drone_a, org_id=org_a, sn=f"A-{uuid4().hex[:8]}", model="X", protocol="mavlink", status="online"),
            Drone(id=drone_b, org_id=org_b, sn=f"B-{uuid4().hex[:8]}", model="X", protocol="mavlink", status="online"),
        ])
        await _seed(db, org_a, drone_a, [("person", 0.9, 1)])
        await _seed(db, org_b, drone_b, [("person", 0.9, 1), ("person", 0.9, 2)])

    async with Session() as db:
        ctx = ToolContext(db=db, org_id=org_a, user_id=uuid4())
        out = await list_detections(ctx, ListDetectionsArgs(limit=10))
    assert out["count"] == 1


@pytest.mark.asyncio
async def test_list_detections_invalid_drone_id_soft_fail(client):
    """Bad UUID returns empty result with a reason — never crashes."""
    from app.db import engine
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        ctx = ToolContext(db=db, org_id=uuid4(), user_id=uuid4())
        out = await list_detections(ctx, ListDetectionsArgs(drone_id="not-a-uuid"))
    assert out["detections"] == []
    assert "invalid" in out.get("reason", "")


@pytest.mark.asyncio
async def test_detection_stats_by_label(client):
    """Aggregate counts per label; top_label reflects the max bucket."""
    from app.db import engine
    Session = async_sessionmaker(engine, expire_on_commit=False)
    org_id = uuid4()
    drone_id = uuid4()
    async with Session() as db:
        db.add(Drone(
            id=drone_id, org_id=org_id, sn=f"SN-{uuid4().hex[:8]}",
            model="X", protocol="mavlink", status="online",
        ))
        await _seed(db, org_id, drone_id, [
            ("person", 0.9, 5),
            ("person", 0.8, 10),
            ("person", 0.7, 20),
            ("vehicle", 0.9, 5),
        ])

    async with Session() as db:
        ctx = ToolContext(db=db, org_id=org_id, user_id=uuid4())
        out = await detection_stats(ctx, DetectionStatsArgs(since_minutes=60))
    assert out["total"] == 4
    assert out["by_label"] == {"person": 3, "vehicle": 1}
    assert out["top_label"] == "person"


@pytest.mark.asyncio
async def test_detection_stats_time_window(client):
    """Rows outside the trailing window are excluded."""
    from app.db import engine
    Session = async_sessionmaker(engine, expire_on_commit=False)
    org_id = uuid4()
    drone_id = uuid4()
    async with Session() as db:
        db.add(Drone(
            id=drone_id, org_id=org_id, sn=f"SN-{uuid4().hex[:8]}",
            model="X", protocol="mavlink", status="online",
        ))
        await _seed(db, org_id, drone_id, [
            ("person", 0.9, 1),       # inside
            ("person", 0.9, 45),      # inside 60-min but outside 30-min
            ("vehicle", 0.9, 500),    # far outside
        ])

    async with Session() as db:
        ctx = ToolContext(db=db, org_id=org_id, user_id=uuid4())
        out = await detection_stats(ctx, DetectionStatsArgs(since_minutes=30))
    assert out["total"] == 1
    assert out["by_label"] == {"person": 1}


@pytest.mark.asyncio
async def test_registry_exposes_vision_tools(client):
    """build_default_registry() registers the two new tools with the
    correct permission (non-sensitive)."""
    r = build_default_registry()
    names = set(r.names())
    assert "list_detections" in names
    assert "detection_stats" in names
    for name, spec in r._tools.items():
        if name in ("list_detections", "detection_stats"):
            assert spec.permission != "sensitive"
