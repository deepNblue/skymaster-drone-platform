"""Tests for R21 Step H — Video stream registry."""
from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    from app.services import rate_limit
    rate_limit.reset_bucket()
    yield
    rate_limit.reset_bucket()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_normalize_protocol_variants():
    from app.services.video_streams import normalize_protocol
    assert normalize_protocol("rtsp://cam/1") == "rtsp"
    assert normalize_protocol("rtmp://cdn/live/xyz") == "rtmp"
    assert normalize_protocol("https://cdn/hls.m3u8") == "hls"
    assert normalize_protocol("webrtc://host/room") == "webrtc"
    assert normalize_protocol("") == "rtsp"  # safe default
    assert normalize_protocol("gopher://weird") == "rtsp"


def test_is_stale_thresholds():
    from datetime import datetime, timezone, timedelta
    from app.services.video_streams import is_stale
    assert is_stale(None) is True
    fresh = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert is_stale(fresh, threshold_s=30) is False
    old = datetime.now(timezone.utc) - timedelta(seconds=120)
    assert is_stale(old, threshold_s=30) is True


def test_parse_fps_helper():
    from app.services.video_streams import _parse_fps
    assert _parse_fps("30/1") == 30.0
    assert _parse_fps("60000/1001") is not None
    assert _parse_fps("25") == 25.0
    assert _parse_fps(None) is None
    assert _parse_fps("bad") is None


@pytest.mark.asyncio
async def test_run_ffprobe_missing_binary(monkeypatch):
    import app.services.video_streams as mod
    monkeypatch.setattr(mod.shutil, "which", lambda *_: None)
    result = await mod.run_ffprobe("rtsp://nope/x")
    assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


async def _make_user(client, role: str = "operator") -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    email = f"vs_{role}_{uuid4().hex[:10]}@x.com"
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
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_register_infers_protocol_and_lists(client):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        "/api/v1/video-streams",
        json={
            "name": "D001 前置",
            "source_url": "rtsp://camera.local/live/D001",
            "play_url": "https://cdn.example.com/live/D001.m3u8",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["protocol"] == "rtsp"
    assert body["status"] == "idle"
    sid = body["id"]

    r = await client.get("/api/v1/video-streams", headers=h)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert sid in ids


@pytest.mark.asyncio
async def test_viewer_cannot_register(client):
    tok = await _make_user(client, role="viewer")
    r = await client.post(
        "/api/v1/video-streams",
        json={"name": "x", "source_url": "rtsp://x/y"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_heartbeat_flips_idle_to_active(client):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        "/api/v1/video-streams",
        json={"name": "hb", "source_url": "rtmp://cdn/live/hb"},
        headers=h,
    )
    sid = r.json()["id"]

    r = await client.post(f"/api/v1/video-streams/{sid}/heartbeat", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active"
    assert body["last_seen_at"] is not None
    assert body["stale"] is False


@pytest.mark.asyncio
async def test_stop_sets_stopped(client):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/video-streams",
        json={"name": "s", "source_url": "rtsp://x/y"},
        headers=h,
    )
    sid = r.json()["id"]
    r = await client.post(f"/api/v1/video-streams/{sid}/stop", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"


@pytest.mark.asyncio
async def test_probe_records_result(client, monkeypatch):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        "/api/v1/video-streams",
        json={"name": "pr", "source_url": "rtsp://cam/prob"},
        headers=h,
    )
    sid = r.json()["id"]

    async def _fake_probe(url, timeout_s=5.0):
        return {
            "status": "ok", "codec": "h264",
            "width": 1920, "height": 1080, "fps": 30.0, "bit_rate": 4_500_000,
        }
    from app.api.v1 import video_streams as ep
    monkeypatch.setattr(ep, "run_ffprobe", _fake_probe)

    r = await client.post(f"/api/v1/video-streams/{sid}/probe", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["probe_status"] == "ok"
    assert body["payload"]["codec"] == "h264"

    # Detail row should now carry codec/width/height/bitrate.
    r = await client.get(f"/api/v1/video-streams/{sid}", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["codec"] == "h264"
    assert d["width"] == 1920
    assert d["bitrate_kbps"] == 4500

    r = await client.get(f"/api/v1/video-streams/{sid}/probes", headers=h)
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_probe_error_sets_stream_status_error(client, monkeypatch):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/video-streams",
        json={"name": "pe", "source_url": "rtsp://cam/broken"},
        headers=h,
    )
    sid = r.json()["id"]

    async def _fake_probe(url, timeout_s=5.0):
        return {"status": "error", "reason": "connection refused"}
    from app.api.v1 import video_streams as ep
    monkeypatch.setattr(ep, "run_ffprobe", _fake_probe)

    r = await client.post(f"/api/v1/video-streams/{sid}/probe", headers=h)
    assert r.status_code == 200
    assert r.json()["probe_status"] == "error"

    r = await client.get(f"/api/v1/video-streams/{sid}", headers=h)
    assert r.json()["status"] == "error"


@pytest.mark.asyncio
async def test_stats_summary(client):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}
    # Two streams, different protocols.
    await client.post("/api/v1/video-streams",
                      json={"name": "a", "source_url": "rtsp://a/1"},
                      headers=h)
    await client.post("/api/v1/video-streams",
                      json={"name": "b", "source_url": "rtmp://cdn/b"},
                      headers=h)
    r = await client.get("/api/v1/video-streams/stats/summary", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert "by_status" in data and "by_protocol" in data
    assert data["by_protocol"].get("rtsp", 0) >= 1
    assert data["by_protocol"].get("rtmp", 0) >= 1


@pytest.mark.asyncio
async def test_delete_stream(client):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.post(
        "/api/v1/video-streams",
        json={"name": "d", "source_url": "rtsp://x/y"},
        headers=h,
    )
    sid = r.json()["id"]
    r = await client.delete(f"/api/v1/video-streams/{sid}", headers=h)
    assert r.status_code == 204
    r = await client.get(f"/api/v1/video-streams/{sid}", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_filter_by_status_and_protocol(client):
    tok = await _make_user(client)
    h = {"Authorization": f"Bearer {tok}"}
    r1 = await client.post(
        "/api/v1/video-streams",
        json={"name": "f1", "source_url": "rtsp://x/1"},
        headers=h,
    )
    await client.post(f"/api/v1/video-streams/{r1.json()['id']}/heartbeat", headers=h)

    r2 = await client.post(
        "/api/v1/video-streams",
        json={"name": "f2", "source_url": "rtmp://x/2"},
        headers=h,
    )

    r = await client.get("/api/v1/video-streams?status=active", headers=h)
    ids = [s["id"] for s in r.json()]
    assert r1.json()["id"] in ids
    assert r2.json()["id"] not in ids

    r = await client.get("/api/v1/video-streams?protocol=rtmp", headers=h)
    ids = [s["id"] for s in r.json()]
    assert r2.json()["id"] in ids
