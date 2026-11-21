"""Unit tests for the 4DGS (v2.1 D2.1) additions to scene_executors."""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.scene_executors import (
    ExecutorConfig,
    Gsplat4DExecutor,
    build_gsplat4d_cmd,
    parse_gsplat4d_stats,
)


class _Runner:
    def __init__(self, ok=True, stdout="", stderr="", exit_code=0):
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code

    async def run(self, cmd, cwd, timeout):  # noqa: ARG002
        class _R:
            pass
        r = _R()
        r.ok = self.ok
        r.stdout = self.stdout
        r.stderr = self.stderr
        r.exit_code = self.exit_code
        return r


# ---- build_gsplat4d_cmd -----------------------------------------------------


def test_build_gsplat4d_cmd_native():
    cfg = ExecutorConfig(use_docker=False)
    cmd = build_gsplat4d_cmd(cfg, Path("/tmp/scene-x"), n_frames=8)
    assert "splatfacto-4d" in cmd
    assert "--n-frames" in cmd
    assert cmd[cmd.index("--n-frames") + 1] == "8"
    assert cmd[cmd.index("--data") + 1] == "/tmp/scene-x"


def test_build_gsplat4d_cmd_docker():
    cfg = ExecutorConfig(use_docker=True, docker_image_gsplat="gsplat:v1")
    cmd = build_gsplat4d_cmd(cfg, Path("/tmp/scene-x"), n_frames=12)
    assert cmd[0] == "docker"
    assert "--gpus" in cmd
    assert "all" in cmd
    assert "-v" in cmd
    assert "/tmp/scene-x:/work" in cmd
    assert "gsplat:v1" in cmd
    assert "--n-frames" in cmd
    assert cmd[cmd.index("--n-frames") + 1] == "12"


# ---- parse_gsplat4d_stats ---------------------------------------------------


def test_parse_gsplat4d_stats_json_line():
    stdout = (
        "some noise\n"
        '{"n_gaussians": 250000, "psnr": 27.5}\n'
        "psnr_temporal: 24.3\n"
        "n_frames: 16\n"
    )
    got = parse_gsplat4d_stats(stdout)
    assert got["n_gaussians"] == 250000
    assert abs(got["psnr"] - 27.5) < 1e-9
    assert abs(got["psnr_temporal"] - 24.3) < 1e-9
    assert got["n_frames"] == 16


def test_parse_gsplat4d_stats_plain_kv():
    stdout = (
        "n_gaussians: 100000\n"
        "psnr: 26.0\n"
        "psnr_temporal: 22.7\n"
        "n_frames: 4\n"
    )
    got = parse_gsplat4d_stats(stdout)
    assert got["n_gaussians"] == 100000
    assert abs(got["psnr"] - 26.0) < 1e-9
    assert abs(got["psnr_temporal"] - 22.7) < 1e-9
    assert got["n_frames"] == 4


def test_parse_gsplat4d_stats_missing_temporal_is_none():
    # 3dgs-style output only
    stdout = "n_gaussians: 50000\npsnr: 25.0\n"
    got = parse_gsplat4d_stats(stdout)
    assert got["n_gaussians"] == 50000
    assert got["psnr_temporal"] is None
    assert got["n_frames"] is None


# ---- Gsplat4DExecutor -------------------------------------------------------


def test_set_frame_count_validates():
    ex = Gsplat4DExecutor()
    ex.set_frame_count(1)
    ex.set_frame_count(64)
    with pytest.raises(ValueError):
        ex.set_frame_count(0)
    with pytest.raises(ValueError):
        ex.set_frame_count(-3)


async def test_run_training_populates_temporal_fields(tmp_path):
    ex = Gsplat4DExecutor(
        cfg=ExecutorConfig(use_docker=False, scenes_workdir=str(tmp_path))
    )
    ex.set_frame_count(8)
    fake_stdout = (
        "training start\n"
        '{"n_gaussians": 300000, "psnr": 28.1}\n'
        "psnr_temporal: 25.0\n"
        "n_frames: 8\n"
    )
    with patch(
        "app.services.scene_executors.get_runner",
        return_value=_Runner(ok=True, stdout=fake_stdout),
    ):
        r = await ex.run_training(uuid4())
    assert r.ok
    assert r.n_gaussians == 300000
    assert abs(r.psnr_train - 28.1) < 1e-9
    assert r.n_frames == 8
    assert abs(r.psnr_temporal - 25.0) < 1e-9


async def test_run_training_propagates_failure(tmp_path):
    ex = Gsplat4DExecutor(
        cfg=ExecutorConfig(use_docker=False, scenes_workdir=str(tmp_path))
    )
    ex.set_frame_count(4)
    with patch(
        "app.services.scene_executors.get_runner",
        return_value=_Runner(
            ok=False, exit_code=127, stderr="oom @ frame 3", stdout=""
        ),
    ):
        r = await ex.run_training(uuid4())
    assert not r.ok
    assert "exit=127" in r.error
    assert "oom" in r.error


async def test_run_training_uses_frame_count_in_command(tmp_path):
    """The n_frames set via set_frame_count() should reach the CLI."""
    ex = Gsplat4DExecutor(
        cfg=ExecutorConfig(use_docker=False, scenes_workdir=str(tmp_path))
    )
    ex.set_frame_count(24)
    captured = {}

    class _Cap:
        async def run(self, cmd, cwd, timeout):  # noqa: ARG002
            captured["cmd"] = cmd

            class _R:
                ok = True
                stdout = ""
                stderr = ""
                exit_code = 0

            return _R()

    with patch(
        "app.services.scene_executors.get_runner", return_value=_Cap()
    ):
        await ex.run_training(uuid4())
    assert "--n-frames" in captured["cmd"]
    idx = captured["cmd"].index("--n-frames")
    assert captured["cmd"][idx + 1] == "24"
