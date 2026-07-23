"""D3.1 · Scene frame tests — 4DGS timeline management."""
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
            id=uid, email=f"frame+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid, org


async def _mk_4dgs_scene(client, tok: str) -> UUID:
    r = await client.post(
        "/api/v1/scenes", headers=_h(tok),
        json={
            "name": "frame-test", "scene_kind": "4dgs", "n_frames": 20,
        },
    )
    assert r.status_code == 201, r.text
    return UUID(r.json()["id"])


async def _mk_3dgs_scene(client, tok: str) -> UUID:
    r = await client.post(
        "/api/v1/scenes", headers=_h(tok),
        json={"name": "3dgs-test", "scene_kind": "3dgs"},
    )
    assert r.status_code == 201, r.text
    return UUID(r.json()["id"])


# --------------------------------------------------------------------- #
# Create + get + list
# --------------------------------------------------------------------- #

async def test_create_and_get_frame(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={
            "frame_index": 5,
            "captured_at": now.isoformat(),
            "is_keyframe": True,
            "psnr_frame": 28.5,
            "lighting": "day",
            "notes": "first stable frame",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["frame_index"] == 5
    assert body["is_keyframe"] is True
    assert body["psnr_frame"] == 28.5
    assert body["lighting"] == "day"

    r = await client.get(
        f"/api/v1/scenes/{sid}/frames/5", headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["frame_index"] == 5


async def test_reject_frame_on_3dgs_scene(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_3dgs_scene(client, tok)
    r = await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 0},
    )
    assert r.status_code == 400
    assert "not 4dgs" in r.text


async def test_frame_index_must_be_nonneg(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    r = await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": -1},
    )
    # Pydantic ge=0 kicks in first, so 422.
    assert r.status_code == 422


async def test_duplicate_frame_index_fails(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    r1 = await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 3},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 3},
    )
    assert r2.status_code == 400  # unique constraint


async def test_invalid_lighting_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    r = await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 0, "lighting": "solar-eclipse"},
    )
    assert r.status_code == 400
    assert "invalid lighting" in r.text


# --------------------------------------------------------------------- #
# Bulk create
# --------------------------------------------------------------------- #

async def test_bulk_create_ordered(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    now = datetime.now(timezone.utc)
    frames = [
        {
            "frame_index": i,
            "captured_at": (now + timedelta(seconds=i)).isoformat(),
            "is_keyframe": i % 5 == 0,
            "psnr_frame": 25.0 + 0.1 * i,
        }
        for i in range(10)
    ]
    r = await client.post(
        f"/api/v1/scenes/{sid}/frames/bulk", headers=_h(tok),
        json={"frames": frames},
    )
    assert r.status_code == 201
    assert len(r.json()) == 10

    r = await client.get(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
    )
    rows = r.json()
    assert len(rows) == 10
    # ordered ASC by frame_index
    assert [f["frame_index"] for f in rows] == list(range(10))
    # keyframes are 0 and 5
    assert [f["frame_index"] for f in rows if f["is_keyframe"]] == [0, 5]


# --------------------------------------------------------------------- #
# List / filter
# --------------------------------------------------------------------- #

async def test_list_only_keyframes_filter(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    for i in range(6):
        await client.post(
            f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
            json={"frame_index": i, "is_keyframe": i in (0, 3)},
        )
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames?only_keyframes=true",
        headers=_h(tok),
    )
    idx = [f["frame_index"] for f in r.json()]
    assert idx == [0, 3]


async def test_list_lighting_filter(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 0, "lighting": "day"},
    )
    await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 1, "lighting": "night"},
    )
    await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 2, "lighting": "day"},
    )
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames?lighting=day", headers=_h(tok),
    )
    idx = [f["frame_index"] for f in r.json()]
    assert idx == [0, 2]


# --------------------------------------------------------------------- #
# Update + delete
# --------------------------------------------------------------------- #

async def test_update_frame_marks_keyframe(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 7, "psnr_frame": 22.0},
    )
    r = await client.patch(
        f"/api/v1/scenes/{sid}/frames/7", headers=_h(tok),
        json={
            "is_keyframe": True,
            "psnr_frame": 30.0,
            "notes": "incident moment",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_keyframe"] is True
    assert body["psnr_frame"] == 30.0
    assert body["notes"] == "incident moment"


async def test_delete_frame(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok),
        json={"frame_index": 9},
    )
    r = await client.delete(
        f"/api/v1/scenes/{sid}/frames/9", headers=_h(tok),
    )
    assert r.status_code == 204
    r = await client.get(
        f"/api/v1/scenes/{sid}/frames/9", headers=_h(tok),
    )
    assert r.status_code == 404


# --------------------------------------------------------------------- #
# Timeline summary
# --------------------------------------------------------------------- #

async def test_timeline_summary_aggregates(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    frames = []
    for i in range(6):
        frames.append({
            "frame_index": i,
            "captured_at": (now + timedelta(seconds=i * 10)).isoformat(),
            "is_keyframe": i in (0, 2, 5),
            "psnr_frame": 20.0 + i,
            "lighting": "day",
        })
    r = await client.post(
        f"/api/v1/scenes/{sid}/frames/bulk", headers=_h(tok),
        json={"frames": frames},
    )
    assert r.status_code == 201

    r = await client.get(
        f"/api/v1/scenes/{sid}/timeline", headers=_h(tok),
    )
    body = r.json()
    assert body["total_frames"] == 6
    assert body["keyframe_count"] == 3
    assert body["keyframe_indices"] == [0, 2, 5]
    # avg PSNR: mean of 20..25 = 22.5
    assert abs(body["avg_psnr"] - 22.5) < 0.001
    assert body["captured_at_start"] is not None
    assert body["captured_at_end"] is not None


async def test_timeline_empty_scene(client) -> None:
    tok, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok)
    r = await client.get(
        f"/api/v1/scenes/{sid}/timeline", headers=_h(tok),
    )
    body = r.json()
    assert body["total_frames"] == 0
    assert body["keyframe_count"] == 0
    assert body["keyframe_indices"] == []
    assert body["avg_psnr"] is None


# --------------------------------------------------------------------- #
# Cross-org isolation
# --------------------------------------------------------------------- #

async def test_cross_org_scene_not_found(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    sid = await _mk_4dgs_scene(client, tok_a)

    # B tries to create a frame on A's scene.
    r = await client.post(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok_b),
        json={"frame_index": 0},
    )
    assert r.status_code == 404

    r = await client.get(
        f"/api/v1/scenes/{sid}/frames", headers=_h(tok_b),
    )
    assert r.status_code == 404


async def test_missing_scene_404(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.get(
        f"/api/v1/scenes/{uuid4()}/timeline", headers=_h(tok),
    )
    assert r.status_code == 404
