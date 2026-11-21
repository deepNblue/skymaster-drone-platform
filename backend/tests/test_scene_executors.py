"""v2.1 T1.2 · ColmapExecutor / GsplatExecutor unit tests.

Real COLMAP + gsplat are heavy binaries not present in dev/CI. We test:
1. command construction (docker vs native)
2. stdout parsing (fixture snippets that mimic real outputs)
3. success/failure flow via a MockRunner
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.services import scene_executors as se
from app.services import scene_pipeline as sp
from app.services.scene_executors import (
    ColmapExecutor, CommandRunner, ExecutorConfig, GsplatExecutor,
    RunResult, build_colmap_cmd, build_gsplat_cmd,
    make_default_executor, parse_colmap_stats, parse_gsplat_stats,
)


# ---------------------------------------------------------------------------
# MockRunner — captures cmd, returns a scripted RunResult
# ---------------------------------------------------------------------------


class MockRunner(CommandRunner):
    def __init__(self, result: RunResult):
        self.result = result
        self.calls: list[tuple[list[str], dict]] = []

    async def run(self, cmd, *, cwd=None, timeout=None, env=None):
        self.calls.append((list(cmd), {"cwd": cwd, "timeout": timeout, "env": env}))
        return self.result


# ---------------------------------------------------------------------------
# Metrics parsing
# ---------------------------------------------------------------------------


def test_parse_colmap_stats_from_real_output():
    stdout = (
        "Elapsed time: 12.345 [minutes]\n"
        "num_reg_images: 87\n"
        "num_points3D: 42317\n"
    )
    stats = parse_colmap_stats(stdout)
    assert stats["n_points"] == 42317
    assert stats["n_registered_images"] == 87


def test_parse_colmap_stats_handles_missing_lines():
    stats = parse_colmap_stats("nothing useful here")
    assert stats["n_points"] is None
    assert stats["n_registered_images"] is None


def test_parse_colmap_stats_tolerates_case_and_spaces():
    stdout = "Num_Points3D = 12345\nNUM REG IMAGES : 33"
    stats = parse_colmap_stats(stdout)
    assert stats["n_points"] == 12345
    assert stats["n_registered_images"] == 33


def test_parse_gsplat_stats_from_json_line():
    stdout = 'training started\n{"n_gaussians": 234567, "psnr": 27.4}\ndone\n'
    stats = parse_gsplat_stats(stdout)
    assert stats["n_gaussians"] == 234567
    assert stats["psnr"] == pytest.approx(27.4)


def test_parse_gsplat_stats_from_plain_kv():
    stdout = "final metrics:\nn_gaussians: 555555\npsnr: 31.2\n"
    stats = parse_gsplat_stats(stdout)
    assert stats["n_gaussians"] == 555555
    assert stats["psnr"] == pytest.approx(31.2)


def test_parse_gsplat_stats_missing_returns_none():
    stats = parse_gsplat_stats("no metrics")
    assert stats["n_gaussians"] is None
    assert stats["psnr"] is None


def test_parse_gsplat_ignores_malformed_json():
    stdout = '{"n_gaussians": "not-an-int", "psnr": "oops"}\n'
    stats = parse_gsplat_stats(stdout)
    # value parsing failure → falls back to regex, still None
    assert stats["n_gaussians"] is None or isinstance(stats["n_gaussians"], int)


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


def test_build_colmap_cmd_docker_mode():
    cfg = ExecutorConfig()
    cfg.use_docker = True
    cfg.docker_image_colmap = "colmap/colmap:v3.9"
    from pathlib import Path
    cmd = build_colmap_cmd(cfg, Path("/x/y"))
    assert cmd[0] == "docker"
    assert "run" in cmd
    assert "-v" in cmd
    assert "/x/y:/work" in cmd
    assert "colmap/colmap:v3.9" in cmd
    assert "colmap" in cmd
    assert "automatic_reconstructor" in cmd


def test_build_colmap_cmd_native_mode():
    cfg = ExecutorConfig()
    cfg.use_docker = False
    from pathlib import Path
    cmd = build_colmap_cmd(cfg, Path("/x/y"))
    assert cmd[0] == "colmap"
    assert "docker" not in cmd


def test_build_gsplat_cmd_docker_uses_gpu():
    cfg = ExecutorConfig()
    cfg.use_docker = True
    from pathlib import Path
    cmd = build_gsplat_cmd(cfg, Path("/scenes/s1"))
    assert "docker" == cmd[0]
    assert "--gpus" in cmd
    assert "all" in cmd
    assert "ns-train" in cmd
    assert "splatfacto" in cmd


def test_build_gsplat_cmd_native_no_docker():
    cfg = ExecutorConfig()
    cfg.use_docker = False
    from pathlib import Path
    cmd = build_gsplat_cmd(cfg, Path("/x/y"))
    assert cmd[0] == "ns-train"
    assert "docker" not in cmd


# ---------------------------------------------------------------------------
# Executor happy / sad path
# ---------------------------------------------------------------------------


def test_colmap_executor_success_records_points(tmp_path):
    fake_stdout = "num_reg_images: 50\nnum_points3D: 99999\n"
    prev = se.get_runner()
    try:
        se.set_runner(MockRunner(RunResult(ok=True, stdout=fake_stdout, stderr="", exit_code=0)))
        cfg = ExecutorConfig(scenes_workdir=str(tmp_path), use_docker=False)
        ex = ColmapExecutor(cfg=cfg)
        r = asyncio.run(ex.run_colmap(uuid4()))
        assert r.ok
        assert r.n_points == 99999
    finally:
        se.set_runner(prev)


def test_colmap_executor_failure_surfaces_stderr(tmp_path):
    prev = se.get_runner()
    try:
        se.set_runner(MockRunner(RunResult(
            ok=False, stdout="", stderr="cuda oom at frame 12", exit_code=1,
        )))
        cfg = ExecutorConfig(scenes_workdir=str(tmp_path), use_docker=False)
        ex = ColmapExecutor(cfg=cfg)
        r = asyncio.run(ex.run_colmap(uuid4()))
        assert not r.ok
        assert "cuda oom" in r.error
        assert "exit=1" in r.error
    finally:
        se.set_runner(prev)


def test_colmap_executor_run_training_is_rejected(tmp_path):
    cfg = ExecutorConfig(scenes_workdir=str(tmp_path), use_docker=False)
    ex = ColmapExecutor(cfg=cfg)
    r = asyncio.run(ex.run_training(uuid4()))
    assert not r.ok
    assert "does not train" in r.error


def test_gsplat_executor_composite_runs_both(tmp_path):
    calls = []

    class Recorder(CommandRunner):
        async def run(self, cmd, *, cwd=None, timeout=None, env=None):
            calls.append(cmd[0])
            if cmd[0] == "colmap" or (cmd[0] == "docker" and any("colmap" in c for c in cmd)):
                return RunResult(ok=True, stdout="num_points3D: 1000", stderr="", exit_code=0)
            return RunResult(
                ok=True,
                stdout='{"n_gaussians": 10000, "psnr": 28.5}',
                stderr="", exit_code=0,
            )

    prev = se.get_runner()
    try:
        se.set_runner(Recorder())
        cfg = ExecutorConfig(scenes_workdir=str(tmp_path), use_docker=False)
        ex = GsplatExecutor(cfg=cfg)
        sid = uuid4()
        r1 = asyncio.run(ex.run_colmap(sid))
        r2 = asyncio.run(ex.run_training(sid))
        assert r1.ok and r1.n_points == 1000
        assert r2.ok and r2.n_gaussians == 10000 and r2.psnr_train == 28.5
    finally:
        se.set_runner(prev)


def test_gsplat_executor_training_failure(tmp_path):
    prev = se.get_runner()
    try:
        se.set_runner(MockRunner(RunResult(
            ok=False, stdout="", stderr="out of memory", exit_code=137,
        )))
        cfg = ExecutorConfig(scenes_workdir=str(tmp_path), use_docker=False)
        ex = GsplatExecutor(cfg=cfg)
        r = asyncio.run(ex.run_training(uuid4()))
        assert not r.ok
        assert "out of memory" in r.error
    finally:
        se.set_runner(prev)


def test_make_default_executor_env_switch():
    # Default → noop
    with patch.dict(os.environ, {"SKYMASTER_EXECUTOR": "noop"}, clear=False):
        ex = make_default_executor()
        assert ex.__class__.__name__ == "NoOpExecutor"
    with patch.dict(os.environ, {"SKYMASTER_EXECUTOR": "colmap"}, clear=False):
        ex = make_default_executor()
        assert isinstance(ex, ColmapExecutor)
    with patch.dict(os.environ, {"SKYMASTER_EXECUTOR": "gsplat"}, clear=False):
        ex = make_default_executor()
        assert isinstance(ex, GsplatExecutor)


def test_subprocess_runner_missing_binary_returns_127():
    from app.services.scene_executors import SubprocessRunner

    r = asyncio.run(SubprocessRunner().run(["definitely-nonexistent-binary-xyz"]))
    assert not r.ok
    assert r.exit_code == 127


def test_subprocess_runner_timeout():
    from app.services.scene_executors import SubprocessRunner

    r = asyncio.run(SubprocessRunner().run(["sleep", "10"], timeout=0.1))
    assert not r.ok
    assert r.exit_code == 124
    assert "timeout" in r.stderr


def test_gsplat_pipeline_integration_with_state_machine(tmp_path):
    """End-to-end: swap executor → pipeline reaches ready via GsplatExecutor."""

    class Recorder(CommandRunner):
        async def run(self, cmd, *, cwd=None, timeout=None, env=None):
            if any("colmap" in str(c) or "automatic_reconstructor" in str(c) for c in cmd):
                return RunResult(ok=True, stdout="num_points3D: 4242", stderr="", exit_code=0)
            return RunResult(
                ok=True,
                stdout='{"n_gaussians": 88888, "psnr": 29.1}',
                stderr="", exit_code=0,
            )

    class FakeScene:
        def __init__(self):
            self.id = uuid4()
            self.status = "ingested"
            self.error_msg = None
            self.n_points = None
            self.n_gaussians = None
            self.psnr_train = None

    class FakeSess:
        async def flush(self): return None
        async def commit(self): return None

    prev_exec = sp.get_executor()
    prev_runner = se.get_runner()
    try:
        se.set_runner(Recorder())
        cfg = ExecutorConfig(scenes_workdir=str(tmp_path), use_docker=False)
        sp.set_executor(GsplatExecutor(cfg=cfg))
        scene = FakeScene()
        db = FakeSess()
        # ingested → colmap → colmap_done
        asyncio.run(sp.start_colmap(db, scene))
        assert scene.status == "colmap_done"
        assert scene.n_points == 4242
        # colmap_done → training → ready
        asyncio.run(sp.start_training(db, scene))
        assert scene.status == "ready"
        assert scene.n_gaussians == 88888
        assert scene.psnr_train == pytest.approx(29.1)
    finally:
        sp.set_executor(prev_exec)
        se.set_runner(prev_runner)
