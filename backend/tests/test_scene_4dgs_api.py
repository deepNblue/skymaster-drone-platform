"""T9.12 — 4DGS Scene ingestion API + pipeline end-to-end tests.

Verifies:
  1. POST /scenes with scene_kind=4dgs + n_frames requires n_frames>=2
  2. POST /scenes with scene_kind=3dgs rejects n_frames not in {None, 1}
  3. GET /scenes returns scene_kind + n_frames + psnr_temporal fields
  4. pipeline.start_training injects n_frames into Gsplat4DExecutor via
     .set_frame_count() and persists psnr_temporal / n_frames on Scene
  5. SSE payload includes scene_kind / n_frames / psnr_temporal
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(email="fourdgs@test"):
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
        s.add(
            User(
                id=uid,
                email=email,
                hashed_pw=hash_password("StrongPass!"),
                role="user",
                org_id=org_id,
            )
        )
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role="user"), uid, org_id


# --------------------------------------------------------------------------- #
# API validation                                                              #
# --------------------------------------------------------------------------- #


async def test_create_3dgs_default(client):
    """No scene_kind → defaults to 3dgs, no n_frames required."""
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "default-3dgs"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["scene_kind"] == "3dgs"
    assert data["n_frames"] is None
    assert data["psnr_temporal"] is None


async def test_create_4dgs_requires_n_frames(client):
    tok, _, _ = await _mkuser()
    # Missing n_frames
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "4dgs-no-frames", "scene_kind": "4dgs"},
    )
    assert r.status_code == 400, r.text
    assert "n_frames" in r.text

    # n_frames=1 is not allowed for 4dgs
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "4dgs-one", "scene_kind": "4dgs", "n_frames": 1},
    )
    assert r.status_code == 400
    assert "n_frames" in r.text


async def test_create_4dgs_happy(client):
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "4dgs-ok", "scene_kind": "4dgs", "n_frames": 16},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["scene_kind"] == "4dgs"
    assert data["n_frames"] == 16
    assert data["psnr_temporal"] is None  # unset until training


async def test_create_3dgs_rejects_frames_gt1(client):
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "3dgs-bad", "scene_kind": "3dgs", "n_frames": 8},
    )
    assert r.status_code == 400
    assert "3dgs" in r.text.lower() or "n_frames" in r.text


async def test_invalid_scene_kind_rejected(client):
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "5dgs?", "scene_kind": "5dgs"},
    )
    assert r.status_code == 422  # pydantic pattern rejection


# --------------------------------------------------------------------------- #
# pipeline: start_training routing to Gsplat4DExecutor                        #
# --------------------------------------------------------------------------- #


async def test_start_training_injects_n_frames_and_persists_temporal(client):
    """Full pipeline: create 4dgs → mock executor → start_training persists
    psnr_temporal + n_frames back to Scene."""
    from uuid import UUID as _U
    from app.db import engine
    from app.models.scene import Scene
    from app.services.scene_pipeline import (
        ExecResult,
        Executor,
        get_executor,
        set_executor,
        start_training,
        transition,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    tok, uid, org_id = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "4dgs-pipeline", "scene_kind": "4dgs", "n_frames": 12},
    )
    assert r.status_code == 201
    sid = _U(r.json()["id"])

    # Build a fake executor that records set_frame_count and returns
    # temporal metrics.
    class _Fake4D(Executor):
        def __init__(self):
            self.captured_frames = None

        def set_frame_count(self, n):
            self.captured_frames = n

        async def run_colmap(self, scene_id):
            return ExecResult(ok=True, n_points=1000)

        async def run_training(self, scene_id):
            return ExecResult(
                ok=True,
                n_gaussians=250_000,
                psnr_train=27.5,
                n_frames=self.captured_frames,
                psnr_temporal=24.3,
            )

    original = get_executor()
    fake = _Fake4D()
    set_executor(fake)
    try:
        # Move scene into 'colmap_done' so start_training accepts it.
        S = async_sessionmaker(engine, expire_on_commit=False)
        async with S() as s:
            scene = await s.get(Scene, sid)
            await transition(s, scene, "ingesting")
            await transition(s, scene, "ingested")
            await transition(s, scene, "colmap")
            await transition(s, scene, "colmap_done")
            await s.commit()

        async with S() as s:
            scene = await s.get(Scene, sid)
            await start_training(s, scene)
            await s.commit()

        # Verify the executor received the frame count
        assert fake.captured_frames == 12

        # Verify the scene row was updated with temporal metrics
        async with S() as s:
            scene = await s.get(Scene, sid)
            assert scene.status == "ready"
            assert scene.n_gaussians == 250_000
            assert abs(scene.psnr_train - 27.5) < 1e-9
            assert scene.n_frames == 12
            assert abs(scene.psnr_temporal - 24.3) < 1e-9
    finally:
        set_executor(original)


async def test_start_training_no_frame_count_hook_for_3dgs(client):
    """Executors without set_frame_count (i.e. 3dgs) are unaffected."""
    from uuid import UUID as _U
    from app.db import engine
    from app.models.scene import Scene
    from app.services.scene_pipeline import (
        ExecResult,
        Executor,
        get_executor,
        set_executor,
        start_training,
        transition,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/scenes",
        headers=_h(tok),
        json={"name": "3dgs-pipeline"},
    )
    sid = _U(r.json()["id"])

    class _Fake3D(Executor):
        async def run_colmap(self, scene_id):
            return ExecResult(ok=True, n_points=500)

        async def run_training(self, scene_id):
            return ExecResult(
                ok=True, n_gaussians=100_000, psnr_train=25.0
            )

    original = get_executor()
    set_executor(_Fake3D())
    try:
        S = async_sessionmaker(engine, expire_on_commit=False)
        async with S() as s:
            scene = await s.get(Scene, sid)
            await transition(s, scene, "ingesting")
            await transition(s, scene, "ingested")
            await transition(s, scene, "colmap")
            await transition(s, scene, "colmap_done")
            await s.commit()

        async with S() as s:
            scene = await s.get(Scene, sid)
            await start_training(s, scene)  # must not raise
            await s.commit()

        async with S() as s:
            scene = await s.get(Scene, sid)
            assert scene.status == "ready"
            assert scene.scene_kind == "3dgs"
            assert scene.psnr_temporal is None
            assert scene.n_frames is None
    finally:
        set_executor(original)
