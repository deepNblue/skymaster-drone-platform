"""T9.15 · Upload endpoint kind policy (size caps + extension filter +
4DGS single-video invariant)."""
from __future__ import annotations

from unittest.mock import patch
from uuid import UUID as _UUID, uuid4

import pytest


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
    email = f"upl+{_u().hex[:6]}@t.local"
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=email,
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org_id,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role="user")


def _sha() -> str:
    """Generate a syntactically valid sha256 hex string."""
    return "a" * 64


async def _create_scene(client, tok, *, scene_kind="3dgs", n_frames=None):
    body = {"name": f"upl-{uuid4().hex[:6]}"}
    if scene_kind != "3dgs":
        body["scene_kind"] = scene_kind
    if n_frames is not None:
        body["n_frames"] = n_frames
    r = await client.post("/api/v1/scenes", headers=_h(tok), json=body)
    assert r.status_code == 201, r.text
    return _UUID(r.json()["id"])


# ============================================================ extension =====


async def test_source_image_rejects_bad_extension(client):
    tok = await _mkuser()
    sid = await _create_scene(client, tok)
    r = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "photo.exe",  # not an image extension
            "kind": "source_image",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r.status_code == 415
    assert "exe" in r.text


async def test_source_image_accepts_jpg(client):
    tok = await _mkuser()
    sid = await _create_scene(client, tok)
    r = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "aerial_042.JPG",  # uppercase must be accepted
            "kind": "source_image",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r.status_code == 201, r.text


async def test_source_video_extension_filter(client):
    tok = await _mkuser()
    sid = await _create_scene(client, tok, scene_kind="4dgs", n_frames=8)
    # .mp4 is allowed
    r_ok = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "clip.mp4",
            "kind": "source_video",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r_ok.status_code == 201

    # .flv is NOT allowed → 415
    sid2 = await _create_scene(client, tok, scene_kind="4dgs", n_frames=8)
    r_bad = await client.post(
        f"/api/v1/scenes/{sid2}/uploads",
        headers=_h(tok),
        json={
            "filename": "clip.flv",
            "kind": "source_video",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r_bad.status_code == 415


async def test_colmap_sparse_accepts_tar_gz(client):
    """Compound extension .tar.gz should be treated as one unit."""
    tok = await _mkuser()
    sid = await _create_scene(client, tok)
    r = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "sparse.tar.gz",
            "kind": "colmap_sparse",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r.status_code == 201, r.text


async def test_log_kind_accepts_any_extension(client):
    tok = await _mkuser()
    sid = await _create_scene(client, tok)
    r = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "run.weirdext",
            "kind": "log",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r.status_code == 201


# ================================================================ size =====


async def test_source_image_size_cap_413(client):
    tok = await _mkuser()
    sid = await _create_scene(client, tok)
    # 200 MiB is the source_image cap → 300 MiB must reject.
    r = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "huge.jpg",
            "kind": "source_image",
            "sha256_hex": _sha(),
            "size_bytes": 300 * 1024 * 1024,
            "total_chunks": 1,
        },
    )
    assert r.status_code == 413
    assert "size" in r.text.lower()


async def test_preview_thumb_hard_cap(client):
    tok = await _mkuser()
    sid = await _create_scene(client, tok)
    # 5 MiB cap; 10 MiB must reject.
    r = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "thumb.png",
            "kind": "preview_thumb",
            "sha256_hex": _sha(),
            "size_bytes": 10 * 1024 * 1024,
            "total_chunks": 1,
        },
    )
    assert r.status_code == 413


# =================================================== 4DGS video invariants =


async def test_source_video_rejected_on_3dgs_scene(client):
    tok = await _mkuser()
    sid = await _create_scene(client, tok)  # 3dgs by default
    r = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "clip.mp4",
            "kind": "source_video",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r.status_code == 409
    assert "4dgs" in r.text.lower()


async def test_4dgs_scene_rejects_second_source_video(client):
    """After a source_video asset already exists, second upload must 409."""
    tok = await _mkuser()
    sid = await _create_scene(client, tok, scene_kind="4dgs", n_frames=8)

    # First upload → OK
    r1 = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "clip.mp4",
            "kind": "source_video",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r1.status_code == 201

    # Directly seed a SceneAsset row to simulate a completed prior video
    # upload (we don't run through the full chunked flow here — the
    # guard-rail only depends on the presence of an asset row).
    from app.db import engine
    from app.models.scene import SceneAsset
    from sqlalchemy.ext.asyncio import async_sessionmaker
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(SceneAsset(
            id=uuid4(), scene_id=sid, kind="source_video",
            filename="prev.mp4",
            storage_path="/tmp/prev.mp4",
            size_bytes=1024,
        ))
        await s.commit()

    # Second upload → 409
    r2 = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "another.mp4",
            "kind": "source_video",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r2.status_code == 409
    assert "already has" in r2.text


# ================================================================ unknown =


async def test_unknown_kind_400(client):
    tok = await _mkuser()
    sid = await _create_scene(client, tok)
    r = await client.post(
        f"/api/v1/scenes/{sid}/uploads",
        headers=_h(tok),
        json={
            "filename": "x.dat",
            "kind": "totally_made_up_kind",
            "sha256_hex": _sha(),
            "size_bytes": 1024,
            "total_chunks": 1,
        },
    )
    assert r.status_code == 400
    assert "unknown" in r.text.lower()
