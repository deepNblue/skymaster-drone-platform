"""T9.17 · Full-stack 4DGS ingest e2e with real ffmpeg.

Combines T9.11-T9.16 into one integration test: create a 4DGS scene,
attach a real synthesised mp4 asset, invoke POST /ingest, and verify
that FrameExtractor actually laid frames on disk under the scenes
workdir and Scene state transitioned to 'ingested'.

Skipped when ffmpeg is not on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from uuid import UUID as _UUID, uuid4

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg / ffprobe not on PATH",
)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _mkuser():
    from uuid import uuid4 as _u
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = _u()
    org_id = _u()
    email = f"e2e+{_u().hex[:6]}@t.local"
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=email,
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org_id,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role="user")


def _make_tiny_mp4(target: Path, seconds: float = 4.0, fps: int = 24) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"testsrc=duration={seconds}:size=64x64:rate={fps}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(target),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"testsrc synth failed: {r.stderr.decode()[-400:]}")


async def _add_video_asset(scene_id: _UUID, storage_path: str, size: int):
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
            size_bytes=size,
        ))
        await s.commit()


async def test_full_4dgs_ingest_with_real_ffmpeg(client, tmp_path):
    """End-to-end: create scene → attach real mp4 → POST /ingest → verify
    frames physically appeared under scenes workdir and status='ingested'."""
    # 1) Point the executor workdir at a fresh tmp dir for this test.
    scenes_root = tmp_path / "scenes"
    scenes_root.mkdir()
    os.environ["SKYMASTER_SCENES_WORKDIR"] = str(scenes_root)

    # 2) Synthesise a 4s@24fps mp4.
    video = tmp_path / "clip.mp4"
    _make_tiny_mp4(video, seconds=4.0)
    assert video.stat().st_size > 0

    # 3) Register user & create a 4DGS scene requesting 8 frames.
    tok = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={
            "name": "e2e-4dgs",
            "scene_kind": "4dgs",
            "n_frames": 8,
        },
    )
    assert r.status_code == 201, r.text
    scene_id = _UUID(r.json()["id"])

    # 4) Attach a source_video asset row pointing at the synthesised mp4.
    await _add_video_asset(scene_id, str(video), video.stat().st_size)

    # 5) Fire the ingest endpoint — this runs the real FrameExtractor
    #    which shells out to ffprobe + ffmpeg for real.
    r2 = await client.post(
        f"/api/v1/scenes/{scene_id}/ingest",
        headers=_h(tok),
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "ingested", body
    assert body["n_source_images"] == 8
    assert body["scene_kind"] == "4dgs"
    assert body["n_frames"] == 8

    # 6) Verify frames physically landed on disk under scenes workdir.
    frames_dir = scenes_root / str(scene_id) / "frames"
    assert frames_dir.is_dir(), f"frames dir missing: {frames_dir}"
    for i in range(8):
        p = frames_dir / f"{i:04d}" / "images" / "000000.jpg"
        assert p.is_file(), f"missing bucket frame: {p}"
        assert p.stat().st_size > 0

    # 7) No stray flat files after bucket split.
    flat = list(frames_dir.glob("*.jpg"))
    assert flat == [], f"unexpected flat files: {flat}"


async def test_full_4dgs_ingest_bad_video_marks_failed(client, tmp_path):
    """End-to-end failure path: attach a corrupt 'mp4' → ingest → 'failed'
    with a real ffprobe error surfaced."""
    scenes_root = tmp_path / "scenes"
    scenes_root.mkdir()
    os.environ["SKYMASTER_SCENES_WORKDIR"] = str(scenes_root)

    # Corrupt file (all zeros with .mp4 extension) — ffprobe must reject.
    bad = tmp_path / "junk.mp4"
    bad.write_bytes(b"\x00" * 500)

    tok = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "e2e-bad", "scene_kind": "4dgs", "n_frames": 4},
    )
    scene_id = _UUID(r.json()["id"])
    await _add_video_asset(scene_id, str(bad), bad.stat().st_size)

    r2 = await client.post(
        f"/api/v1/scenes/{scene_id}/ingest", headers=_h(tok)
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "failed"
    assert body["error_msg"], body
    # The scene must remain in 'failed' — no frames dir populated with
    # any real content (ingest transitioned away before ffmpeg ran).
    frames_dir = scenes_root / str(scene_id) / "frames"
    if frames_dir.exists():
        assert not any(frames_dir.glob("*/images/*.jpg"))
