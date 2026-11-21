"""Opt-in REAL COLMAP SfM smoke test.

Not run by default (needs the ``colmap`` binary on PATH). Enable with::

    SKYMASTER_TEST_REAL_COLMAP=1 pytest tests/test_scene_real_colmap.py -q

This is the one part of the 3DGS pipeline that runs natively on this WSL
box: COLMAP 3.9.1 (CPU) is installed. It verifies the *real* subprocess
path in ``ColmapExecutor`` — generated command → real binary → sparse
model on disk → parseable point count. The gsplat training stage is
covered by mock tests because nerfstudio pins gsplat==1.4.0 (see
docs/3DGS_BACKEND_STATUS.md).
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.services import scene_executors as se
from app.services.scene_executors import (
    ColmapExecutor, ExecutorConfig, build_colmap_cmd, parse_colmap_stats,
)

pytestmark = pytest.mark.skipif(
    not __import__("os").getenv("SKYMASTER_TEST_REAL_COLMAP"),
    reason="set SKYMASTER_TEST_REAL_COLMAP=1 to run real COLMAP",
)


def _colmap_available() -> bool:
    return shutil.which("colmap") is not None


def test_real_colmap_builds_native_command(tmp_path):
    cfg = ExecutorConfig(scenes_workdir=str(tmp_path), use_docker=False)
    cmd = build_colmap_cmd(cfg, tmp_path)
    assert cmd[0] == "colmap"
    assert "automatic_reconstructor" in cmd
    assert str(tmp_path / "images") in cmd


@pytest.mark.asyncio
async def test_real_colmap_reconstructs_synthetic_views(tmp_path):
    if not _colmap_available():
        pytest.skip("colmap binary not on PATH")

    # Generate a deterministic multi-view fixture with the helper script.
    script = Path(__file__).resolve().parents[1] / "scripts" / "gen_colmap_fixture.py"
    images = tmp_path / "images"
    proc = await asyncio.create_subprocess_exec(
        "python3", str(script), "--out", str(images), "--views", "12",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    assert proc.returncode == 0, err.decode()[-500:]
    assert len(list(images.glob("*.jpg"))) >= 8

    # Real COLMAP via the exact command our ColmapExecutor builds.
    workdir = tmp_path / "scene"
    workdir.mkdir()
    cfg = ExecutorConfig(scenes_workdir=str(tmp_path.parent), use_docker=False)
    cmd = build_colmap_cmd(cfg, workdir)
    # Point image dir at our generated views (workdir/images convention).
    img_idx = cmd.index("--image_path") + 1
    cmd[img_idx] = str(images)
    ws_idx = cmd.index("--workspace_path") + 1
    cmd[ws_idx] = str(workdir)

    r = await se.SubprocessRunner().run(cmd, timeout=300)
    assert r.ok, f"colmap failed exit={r.exit_code}: {r.stderr[-600:]}"

    sparse_dir = workdir / "sparse" / "0"
    assert (sparse_dir / "points3D.bin").exists(), "no reconstructed point cloud"
    assert (sparse_dir / "images.bin").exists(), "no camera poses"

    # Reconstruction must be non-trivial (>1 registered view).
    analyzer = await asyncio.create_subprocess_exec(
        "colmap", "model_analyzer", "--path", str(sparse_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await analyzer.communicate()
    text = out.decode(errors="replace")
    assert "Registered images:" in text
    stats = parse_colmap_stats(text)
    # model_analyzer prints "Images: N / Registered images: N"; our parser
    # keys on num_points3D, so assert the raw text has a real point count.
    import re
    m = re.search(r"Points:\s*(\d+)", text)
    assert m and int(m.group(1)) >= 2, text[-400:]
