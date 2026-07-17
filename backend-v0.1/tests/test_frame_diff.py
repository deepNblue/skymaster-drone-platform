"""D3.3 · Frame diff / change detection tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.auth import create_access_token, hash_password
from app.services.frame_diff import compute_diff_between

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"diff+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid, org


async def _mk_4dgs(client, tok: str) -> UUID:
    r = await client.post(
        "/api/v1/scenes", headers=_h(tok),
        json={"name": "diff", "scene_kind": "4dgs", "n_frames": 20},
    )
    return UUID(r.json()["id"])


# --------------------------- Pure function ---------------------------

def test_compute_diff_psnr_medium() -> None:
    a = {"frame_index": 0, "psnr_frame": 30.0}
    b = {"frame_index": 1, "psnr_frame": 26.5}  # drop 3.5 dB
    d = compute_diff_between(a, b)
    assert d["severity"] == "medium"
    assert d["psnr_delta"] == 3.5
    assert any("PSNR" in r for r in d["reasons"])


def test_compute_diff_psnr_critical() -> None:
    a = {"frame_index": 0, "psnr_frame": 30.0}
    b = {"frame_index": 1, "psnr_frame": 22.0}  # drop 8 dB
    d = compute_diff_between(a, b)
    assert d["severity"] == "critical"


def test_compute_diff_psnr_high() -> None:
    a = {"frame_index": 0, "psnr_frame": 30.0}
    b = {"frame_index": 1, "psnr_frame": 24.5}  # drop 5.5 dB (>=4.5)
    d = compute_diff_between(a, b)
    assert d["severity"] == "high"


def test_compute_diff_psnr_none_skipped() -> None:
    a = {"frame_index": 0, "psnr_frame": None}
    b = {"frame_index": 1, "psnr_frame": 30.0}
    d = compute_diff_between(a, b)
    assert d["psnr_delta"] is None
    assert d["severity"] == "info"


def test_compute_diff_lighting_transition() -> None:
    a = {"frame_index": 0, "lighting": "day"}
    b = {"frame_index": 1, "lighting": "night"}
    d = compute_diff_between(a, b)
    assert d["severity"] == "medium"
    assert d["lighting_from"] == "day"
    assert d["lighting_to"] == "night"
    assert any("day" in r for r in d["reasons"])


def test_compute_diff_keyframe_boundary() -> None:
    a = {"frame_index": 0, "is_keyframe": False}
    b = {"frame_index": 1, "is_keyframe": True}
    d = compute_diff_between(a, b)
    assert d["severity"] == "low"


def test_compute_diff_time_gap_high() -> None:
    t0 = datetime.now(timezone.utc)
    a = {"frame_index": 0, "captured_at": t0}
    b = {"frame_index": 1, "captured_at": t0 + timedelta(seconds=120)}
    d = compute_diff_between(a, b)
    assert d["severity"] == "high"
    assert d["time_gap_s"] == 120.0


def test_compute_diff_time_gap_critical() -> None:
    t0 = datetime.now(timezone.utc)
    a = {"frame_index": 0, "captured_at": t0}
    b = {"frame_index": 1, "captured_at": t0 + timedelta(seconds=400)}
    d = compute_diff_between(a, b)
    assert d["severity"] == "critical"


def test_compute_diff_worst_wins() -> None:
    """PSNR high + lighting medium → severity high."""
    t0 = datetime.now(timezone.utc)
    a = {
        "frame_index": 0, "psnr_frame": 30.0,
        "lighting": "day", "captured_at": t0,
    }
    b = {
        "frame_index": 1, "psnr_frame": 25.0,
        "lighting": "night", "captured_at": t0 + timedelta(seconds=10),
    }
    d = compute_diff_between(a, b)
    assert d["severity"] == "high"  # PSNR wins over lighting/medium
    assert len(d["reasons"]) >= 2


def test_compute_diff_no_signals() -> None:
    d = compute_diff_between(
        {"frame_index": 0}, {"frame_index": 1},
    )
    assert d["severity"] == "info"
    assert d["reasons"] == []


def test_compute_diff_custom_thresholds() -> None:
    a = {"frame_index": 0, "psnr_frame": 30.0}
    b = {"frame_index": 1, "psnr_frame": 28.5}  # drop 1.5 dB
    d = compute_diff_between(a, b, psnr_warn=1.0, psnr_crit=2.0)
    assert d["severity"] == "high"  # 1.5 >= 1.5*warn


# --------------------------- REST integration -----------------------

async def _mk_frames(
    client, tok: str, sid: UUID,
    specs: list[tuple[int, float | None, str | None, bool]],
) -> None:
    """specs = [(frame_index, psnr, lighting, is_keyframe), ...]"""
    frames = []
    t0 = datetime.now(timezone.utc)
    for idx, psnr, light, kf in specs:
        frames.append({
            "frame_index": idx,
            "captured_at": (t0 + timedelta(seconds=idx)).isoformat(),
            "psnr_frame": psnr,
            "lighting": light,
            "is_keyframe": kf,
        })
    r = await client.post(
        f"/api/v1/scenes/{sid}/frames/bulk", headers=_h(tok),
        json={"frames": frames},
    )
    assert r.status_code == 201


async def test_diff_between_indices_rest(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs(client, tok)
    await _mk_frames(client, tok, sid, [
        (0, 30.0, "day", False),
        (1, 22.0, "night", True),
    ])
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames/diff?a=0&b=1", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["severity"] == "critical"
    assert body["psnr_delta"] == 8.0
    assert body["lighting_from"] == "day"
    assert body["lighting_to"] == "night"


async def test_diff_missing_frame_404(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs(client, tok)
    await _mk_frames(client, tok, sid, [(0, 30.0, "day", False)])
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames/diff?a=0&b=99",
        headers=_h(tok),
    )
    assert r.status_code == 404


async def test_change_report_walks_timeline(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs(client, tok)
    await _mk_frames(client, tok, sid, [
        (0, 30.0, "day", True),
        (1, 30.1, "day", False),  # noise (below warn)
        (2, 26.0, "day", False),  # medium drop
        (3, 25.9, "day", False),  # noise
        (4, 18.0, "night", True),  # PSNR crit + lighting -> critical
    ])
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames/changes", headers=_h(tok),
    )
    body = r.json()
    assert body["total_frames"] == 5
    assert body["critical_count"] >= 1
    assert body["medium_count"] >= 1
    # The 1→2 transition should appear (medium PSNR drop).
    pairs = [
        (p["from_index"], p["to_index"], p["severity"])
        for p in body["change_points"]
    ]
    assert (1, 2, "medium") in pairs or any(
        p[0] == 1 and p[1] == 2 and p[2] in {"medium", "high"}
        for p in pairs
    )
    # The 3→4 transition should be critical.
    critical_pairs = [
        (p["from_index"], p["to_index"])
        for p in body["change_points"] if p["severity"] == "critical"
    ]
    assert (3, 4) in critical_pairs


async def test_change_report_min_severity_filter(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs(client, tok)
    await _mk_frames(client, tok, sid, [
        (0, 30.0, "day", True),
        (1, 26.5, "day", False),  # medium
        (2, 18.0, "day", False),  # critical drop 8.5
    ])
    # Only critical.
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames/changes?min_severity=critical",
        headers=_h(tok),
    )
    body = r.json()
    assert all(
        p["severity"] == "critical" for p in body["change_points"]
    )
    assert len(body["change_points"]) == 1


async def test_change_report_empty_scene(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs(client, tok)
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames/changes", headers=_h(tok),
    )
    body = r.json()
    assert body["total_frames"] == 0
    assert body["change_points"] == []


async def test_change_report_cross_org_404(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    sid = await _mk_4dgs(client, tok_a)
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames/changes", headers=_h(tok_b),
    )
    assert r.status_code == 404
