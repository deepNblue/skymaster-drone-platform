"""T9.14 · 4DGS ingest end-to-end (video → frames → ingested).

Verifies the wiring between:
  POST /scenes/{id}/ingest  →  FrameExtractor  →  Scene state machine.

We stub FrameExtractor so the tests never touch ffmpeg; we assert the
extractor was called with the correct video path & n_frames, and that
the scene transitions to 'ingested' (success) or 'failed' (each error
branch) accordingly.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID as _UUID, uuid4

import pytest


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(email="ingest4dgs@t"):
    from uuid import uuid4 as _u
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = _u()
    org_id = _u()
    email = email.replace("@", f"+{_u().hex[:6]}@") + ".local"
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=email,
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org_id,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role="user")


async def _add_video_asset(scene_id: _UUID, storage_path: str):
    """Attach a source_video asset row to the scene."""
    from app.db import engine
    from app.models.scene import SceneAsset
    from sqlalchemy.ext.asyncio import async_sessionmaker

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(SceneAsset(
            id=uuid4(),
            scene_id=scene_id,
            kind="source_video",
            filename="clip.mp4",
            storage_path=storage_path,
            size_bytes=1234,
        ))
        await s.commit()


class _FakeExtractor:
    """Records what it was asked to do and returns a canned result."""

    def __init__(self, ok=True, n_frames=8, error=None):
        self.ok = ok
        self._n_frames = n_frames
        self._error = error
        self.captured = None
        # Extractor-facing config sentinel — real FrameExtractor takes
        # cfg kwarg via keyword; mimic it here so the shim call in
        # scenes.py compiles the same way.
        self.cfg = None

    async def extract(self, video, frames_dir, n_frames, duration_seconds=None):
        from app.services.frame_extractor import FrameExtractionResult
        self.captured = {
            "video": Path(video),
            "frames_dir": Path(frames_dir),
            "n_frames": n_frames,
        }
        return FrameExtractionResult(
            ok=self.ok,
            n_frames=self._n_frames if self.ok else 0,
            frames_dir=Path(frames_dir),
            error=self._error,
        )


# ------------------------------------------------------------------ #
# Happy path                                                          #
# ------------------------------------------------------------------ #


async def test_ingest_4dgs_happy_calls_extractor(client, tmp_path):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "4dgs-ingest-ok", "scene_kind": "4dgs", "n_frames": 8},
    )
    assert r.status_code == 201
    sid = _UUID(r.json()["id"])

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fakevideo")
    await _add_video_asset(sid, str(video))

    fake = _FakeExtractor(ok=True, n_frames=8)
    with patch("app.services.frame_extractor.FrameExtractor",
               return_value=fake):
        r2 = await client.post(
            f"/api/v1/scenes/{sid}/ingest",
            headers=_h(tok),
        )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["status"] == "ingested"
    assert data["n_source_images"] == 8
    # Extractor invocation captured
    assert fake.captured is not None
    assert fake.captured["video"] == video
    assert fake.captured["n_frames"] == 8
    assert fake.captured["frames_dir"].name == "frames"


# ------------------------------------------------------------------ #
# Failure branches                                                    #
# ------------------------------------------------------------------ #


async def test_ingest_4dgs_missing_video_asset_fails(client):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "4dgs-no-video", "scene_kind": "4dgs", "n_frames": 6},
    )
    sid = _UUID(r.json()["id"])
    # Do NOT attach source_video asset.
    r2 = await client.post(f"/api/v1/scenes/{sid}/ingest", headers=_h(tok))
    assert r2.status_code == 200
    data = r2.json()
    assert data["status"] == "failed"
    assert "source_video" in (data["error_msg"] or "")


async def test_ingest_4dgs_extractor_failure_propagates(client, tmp_path):
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "4dgs-truncated", "scene_kind": "4dgs", "n_frames": 8},
    )
    sid = _UUID(r.json()["id"])
    video = tmp_path / "trunc.mp4"
    video.write_bytes(b"trunc")
    await _add_video_asset(sid, str(video))

    fake = _FakeExtractor(
        ok=False, n_frames=0,
        error="ffmpeg only produced 3/8 frames (possibly truncated)",
    )
    with patch("app.services.frame_extractor.FrameExtractor",
               return_value=fake):
        r2 = await client.post(
            f"/api/v1/scenes/{sid}/ingest", headers=_h(tok)
        )
    assert r2.status_code == 200
    data = r2.json()
    assert data["status"] == "failed"
    assert "3/8" in (data["error_msg"] or "")


# ------------------------------------------------------------------ #
# 3DGS legacy path must be untouched                                  #
# ------------------------------------------------------------------ #


async def test_ingest_3dgs_does_not_run_extractor(client, tmp_path):
    """3dgs scenes must go through the legacy n_source_images branch,
    never invoking FrameExtractor."""
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "3dgs-legacy"},
    )
    sid = _UUID(r.json()["id"])

    # Bump n_source_images so the legacy check passes.
    from app.db import engine
    from app.models.scene import Scene
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        scene = await s.get(Scene, sid)
        scene.n_source_images = 5
        await s.commit()

    # If FrameExtractor is instantiated we'd notice — patch to raise.
    with patch(
        "app.services.frame_extractor.FrameExtractor",
        side_effect=AssertionError(
            "FrameExtractor must NOT be called for 3dgs scenes"
        ),
    ):
        r2 = await client.post(
            f"/api/v1/scenes/{sid}/ingest", headers=_h(tok)
        )
    assert r2.status_code == 200
    assert r2.json()["status"] == "ingested"


async def test_ingest_3dgs_no_images_fails(client):
    """3dgs scene with no source images → failed with legacy message."""
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "3dgs-empty"},
    )
    sid = _UUID(r.json()["id"])
    r2 = await client.post(
        f"/api/v1/scenes/{sid}/ingest", headers=_h(tok)
    )
    assert r2.status_code == 200
    data = r2.json()
    assert data["status"] == "failed"
    assert "no source images" in (data["error_msg"] or "")
