"""3DGS training-artifact collection & registration tests.

Covers the closure that was missing: a produced ``.ply`` on disk becomes a
CAS-backed, downloadable SceneAsset — with config-driven globs, dedup and
non-fatal degradation.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.scene import Scene, SceneAsset
from app.services import object_storage as store
from app.services import scene_artifacts_service as art


@pytest_asyncio.fixture
async def session(client):  # noqa: ARG001 — client ensures schema/engine
    from app.db import engine
    Sess = async_sessionmaker(engine, expire_on_commit=False)
    async with Sess() as s:
        yield s


async def _make_scene(session) -> Scene:
    scene = Scene(id=uuid4(), org_id=uuid4(), name=f"A-{uuid4().hex[:6]}", status="ready")
    session.add(scene)
    await session.commit()
    return scene


@pytest.fixture
def cas_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYMASTER_STORAGE_ROOT", str(tmp_path / "storage"))
    store.set_storage(None)  # force re-init with new root
    yield tmp_path / "storage"
    store.set_storage(None)


def _write_ply(path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    import hashlib
    return hashlib.sha256(payload).hexdigest()


# ---------- collect -------------------------------------------------------


def test_collect_finds_ply_and_splat_by_config_globs(tmp_path):
    out = tmp_path / "gsplat_out"
    (out / "a").mkdir(parents=True)
    (out / "a" / "model.ply").write_bytes(b"ply\nfake")
    (out / "scene.splat").write_bytes(b"splat")
    (out / "notes.txt").write_bytes(b"ignore")
    found = art.collect_output_paths(out, {"auto_register": True})
    names = sorted(p.name for p in found)
    assert names == ["model.ply", "scene.splat"]


def test_collect_disabled_by_config_returns_empty(tmp_path):
    (tmp_path / "m.ply").write_bytes(b"ply")
    assert art.collect_output_paths(tmp_path, {"auto_register": False}) == []


def test_collect_ckpt_only_when_enabled(tmp_path):
    (tmp_path / "m.ply").write_bytes(b"ply")
    (tmp_path / "step.ckpt").write_bytes(b"ckpt")
    plain = art.collect_output_paths(tmp_path, {"auto_register": True})
    assert [p.name for p in plain] == ["m.ply"]
    with_ckpt = art.collect_output_paths(tmp_path, {
        "auto_register": True, "include_ckpt": True,
        "ckpt_globs": ["**/*.ckpt"],
    })
    assert sorted(p.name for p in with_ckpt) == ["m.ply", "step.ckpt"]


def test_kind_by_ext_is_config_driven():
    cfg = {"kind_by_ext": {"ply": "gsplat_ply"}, "include_ckpt": False}
    from pathlib import Path
    assert art._kind_for(Path("a.PLY"), cfg) == "gsplat_ply"
    assert art._kind_for(Path("a.ckpt"), cfg) is None


# ---------- register ------------------------------------------------------


@pytest.mark.asyncio
async def test_register_produced_ply_creates_asset_and_cas(session, tmp_path, cas_root):
    scene = await _make_scene(session)
    ply = tmp_path / "model.ply"
    payload = b"ply\nformat binary_little_endian 1.0\n" + b"\x00" * 2048
    sha = _write_ply(ply, payload)

    result = await art.register_produced_artifacts(session, scene, [str(ply)])
    assert len(result.registered) == 1
    assert result.registered[0]["sha256_hex"] == sha
    assert result.registered[0]["kind"] == "gsplat_ply"
    assert not result.errors

    rows = (await session.execute(
        select(SceneAsset).where(SceneAsset.scene_id == scene.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].filename == "model.ply"
    assert rows[0].uploaded_by is None
    assert (cas_root / "cas" / sha[:2] / sha[2:]).exists()


@pytest.mark.asyncio
async def test_register_is_idempotent_by_sha(session, tmp_path, cas_root):
    scene = await _make_scene(session)
    ply = tmp_path / "model.ply"
    _write_ply(ply, b"ply\nsame-bytes")
    first = await art.register_produced_artifacts(session, scene, [str(ply)])
    second = await art.register_produced_artifacts(session, scene, [str(ply)])
    assert len(first.registered) == 1
    assert len(second.registered) == 0
    assert second.skipped[0]["reason"] == "duplicate"


@pytest.mark.asyncio
async def test_register_skips_missing_and_unknown_ext(session, tmp_path, cas_root):
    scene = await _make_scene(session)
    unknown = tmp_path / "readme.txt"
    unknown.write_bytes(b"hi")
    result = await art.register_produced_artifacts(
        session, scene, [str(tmp_path / "gone.ply"), str(unknown)]
    )
    reasons = {s["reason"] for s in result.skipped}
    assert {"missing", "unknown_ext"} <= reasons
    assert result.registered == []


@pytest.mark.asyncio
async def test_register_non_fatal_on_cas_error(session, tmp_path, cas_root, monkeypatch):
    scene = await _make_scene(session)
    ply = tmp_path / "model.ply"
    _write_ply(ply, b"ply\nboom")

    def boom(*a, **k):
        raise RuntimeError("cas down")

    monkeypatch.setattr(art, "_import_file_into_cas", boom)
    result = await art.register_produced_artifacts(session, scene, [str(ply)])
    assert result.registered == []
    assert len(result.errors) == 1
    assert "cas down" in result.errors[0]["error"]


@pytest.mark.asyncio
async def test_register_respects_disabled_config(session, tmp_path, cas_root, monkeypatch):
    scene = await _make_scene(session)
    ply = tmp_path / "model.ply"
    _write_ply(ply, b"ply\noff")
    monkeypatch.setattr(art, "_artifact_cfg", lambda: {"auto_register": False})
    result = await art.register_produced_artifacts(session, scene, [str(ply)])
    assert result.as_dict() == {"registered": [], "skipped": [], "errors": []}


# ---------- pipeline integration -----------------------------------------


@pytest.mark.asyncio
async def test_pipeline_registers_artifact_then_transitions_ready(session, tmp_path, monkeypatch):
    from app.services import scene_pipeline as sp

    scene = Scene(id=uuid4(), org_id=uuid4(), name="P-PL", status="colmap_done")
    session.add(scene)
    await session.commit()
    ply = tmp_path / "trained.ply"
    _write_ply(ply, b"ply\ntrained-output")

    class ArtifactExecutor(sp.Executor):
        async def run_colmap(self, scene_id):  # noqa: ARG002
            return sp.ExecResult(ok=True)

        async def run_training(self, scene_id):  # noqa: ARG002
            return sp.ExecResult(
                ok=True, n_gaussians=100, psnr_train=30.0,
                artifact_paths=[str(ply)],
            )

    prev = sp.get_executor()
    try:
        sp.set_executor(ArtifactExecutor())
        out = await sp.start_training(session, scene)
    finally:
        sp.set_executor(prev)

    assert out.status == "ready"
    assert scene.meta["training_artifacts"]["registered"][0]["filename"] == "trained.ply"
    rows = (await session.execute(
        select(SceneAsset).where(SceneAsset.scene_id == scene.id)
    )).scalars().all()
    assert len(rows) == 1
