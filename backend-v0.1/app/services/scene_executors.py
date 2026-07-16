"""COLMAP / gsplat executor implementations — v2.1 T1.2 / T1.3.

We inherit the ``Executor`` protocol from ``scene_pipeline`` and add two
subprocess-based backends:

* ``ColmapExecutor``  — invokes COLMAP SfM to produce a sparse point cloud
                        + camera poses from the scene's source images.
* ``GsplatExecutor``  — invokes a Gaussian splatting trainer (nerfstudio
                        or Inria original) using the COLMAP output.

Both are designed so that:

1. **No hard dependency** on docker/colmap being installed. The runner is
   pluggable (``CommandRunner`` protocol), which we mock in tests.
2. **Env-driven**. Pick backend + docker image + workdir via env vars.
3. **Metrics parsing** is isolated in pure functions so we can test it
   against captured stdout snippets from real runs.

Why not just call the binaries directly?
----------------------------------------
On WSL/dev boxes we typically don't have COLMAP compiled. In prod each
scene worker will run inside a GPU-enabled container that has COLMAP +
gsplat pre-installed. The ``docker exec``/``docker run`` wrapper is the
minimum sane isolation boundary for user-uploaded source data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence
from uuid import UUID

from app.services.scene_pipeline import ExecResult, Executor

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Command runner — subprocess boundary we can mock
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int


class CommandRunner(ABC):
    @abstractmethod
    async def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        env: Optional[dict[str, str]] = None,
    ) -> RunResult: ...


class SubprocessRunner(CommandRunner):
    """Real runner using asyncio subprocess."""

    async def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        env: Optional[dict[str, str]] = None,
    ) -> RunResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            return RunResult(ok=False, stdout="", stderr=str(e), exit_code=127)

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return RunResult(
                ok=False, stdout="", stderr=f"timeout after {timeout}s", exit_code=124
            )
        rc = proc.returncode or 0
        return RunResult(
            ok=(rc == 0),
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            exit_code=rc,
        )


_default_runner: CommandRunner = SubprocessRunner()


def get_runner() -> CommandRunner:
    return _default_runner


def set_runner(r: CommandRunner) -> None:  # test hook
    global _default_runner
    _default_runner = r


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ExecutorConfig:
    # Use ``default_factory`` so each ExecutorConfig() re-reads the
    # environment. Bare ``= os.getenv(...)`` would freeze the value at
    # class-definition time — which broke pytest-driven env overrides
    # (e.g. SKYMASTER_SCENES_WORKDIR pointing to a tmp_path in e2e tests).
    docker_image_colmap: str = field(
        default_factory=lambda: os.getenv(
            "SKYMASTER_COLMAP_IMAGE", "colmap/colmap:latest"
        )
    )
    docker_image_gsplat: str = field(
        default_factory=lambda: os.getenv(
            "SKYMASTER_GSPLAT_IMAGE", "nerfstudio/nerfstudio:latest"
        )
    )
    scenes_workdir: str = field(
        default_factory=lambda: os.getenv(
            "SKYMASTER_SCENES_WORKDIR", "/tmp/skymaster-scenes"
        )
    )
    colmap_timeout: float = field(
        default_factory=lambda: float(
            os.getenv("SKYMASTER_COLMAP_TIMEOUT", "7200")
        )
    )
    gsplat_timeout: float = field(
        default_factory=lambda: float(
            os.getenv("SKYMASTER_GSPLAT_TIMEOUT", "14400")
        )
    )
    use_docker: bool = field(
        default_factory=lambda: os.getenv(
            "SKYMASTER_USE_DOCKER", "1"
        ) in ("1", "true", "TRUE")
    )


def _scene_workdir(cfg: ExecutorConfig, scene_id: UUID) -> Path:
    p = Path(cfg.scenes_workdir) / str(scene_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Metrics parsing (pure functions — heavily unit tested)
# ---------------------------------------------------------------------------


# COLMAP prints "num_reg_images: X" and "num_points3D: Y" at end of sparse SfM
_COLMAP_POINTS_RE = re.compile(r"num[_\s]*points3?D?\s*[:=]\s*(\d+)", re.IGNORECASE)
_COLMAP_IMAGES_RE = re.compile(r"num[_\s]*reg[_\s]*images?\s*[:=]\s*(\d+)", re.IGNORECASE)


def parse_colmap_stats(stdout: str) -> dict:
    """Extract n_points, n_registered_images from COLMAP mapper output."""
    n_points: Optional[int] = None
    n_reg: Optional[int] = None
    m = _COLMAP_POINTS_RE.search(stdout)
    if m:
        n_points = int(m.group(1))
    m = _COLMAP_IMAGES_RE.search(stdout)
    if m:
        n_reg = int(m.group(1))
    return {"n_points": n_points, "n_registered_images": n_reg}


# gsplat / nerfstudio typically print JSON summary at end of training
_GSPLAT_JSON_LINE = re.compile(r"^\s*\{.*(gaussians|psnr).*\}\s*$", re.IGNORECASE)


def parse_gsplat_stats(stdout: str) -> dict:
    """Extract n_gaussians, psnr from trainer stdout.

    Two shapes tolerated:
      * a JSON blob line: {"n_gaussians": 234567, "psnr": 27.4}
      * plain "n_gaussians: 234567\\npsnr: 27.4"
    """
    n_gaussians: Optional[int] = None
    psnr: Optional[float] = None

    for line in stdout.splitlines():
        if _GSPLAT_JSON_LINE.match(line):
            try:
                blob = json.loads(line.strip())
                if isinstance(blob, dict):
                    if "n_gaussians" in blob:
                        n_gaussians = int(blob["n_gaussians"])
                    if "psnr" in blob:
                        psnr = float(blob["psnr"])
                    if n_gaussians is not None:
                        break
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

    if n_gaussians is None:
        m = re.search(r"n_gaussians\s*[:=]\s*(\d+)", stdout, re.IGNORECASE)
        if m:
            n_gaussians = int(m.group(1))
    if psnr is None:
        m = re.search(r"psnr\s*[:=]\s*([\d.]+)", stdout, re.IGNORECASE)
        if m:
            try:
                psnr = float(m.group(1))
            except ValueError:
                pass

    return {"n_gaussians": n_gaussians, "psnr": psnr}


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


def build_colmap_cmd(cfg: ExecutorConfig, workdir: Path) -> list[str]:
    """Build COLMAP feature+mapper pipeline command.

    In docker mode: mounts workdir into /work, runs COLMAP CLI.
    In native mode: expects `colmap` on PATH.

    We use the "automatic reconstructor" one-liner which chains:
        feature_extractor → exhaustive_matcher → mapper.
    """
    inner = [
        "colmap", "automatic_reconstructor",
        "--workspace_path", "/work" if cfg.use_docker else str(workdir),
        "--image_path", "/work/images" if cfg.use_docker else str(workdir / "images"),
        "--sparse", "1",
        "--dense", "0",
    ]
    if cfg.use_docker:
        return [
            "docker", "run", "--rm",
            "-v", f"{workdir}:/work",
            cfg.docker_image_colmap,
            *inner,
        ]
    return inner


def build_gsplat_cmd(cfg: ExecutorConfig, workdir: Path) -> list[str]:
    """Build gsplat training command (nerfstudio-style)."""
    inner = [
        "ns-train", "splatfacto",
        "--data", "/work" if cfg.use_docker else str(workdir),
        "--output-dir", "/work/gsplat_out" if cfg.use_docker else str(workdir / "gsplat_out"),
        "--max-num-iterations", "30000",
    ]
    if cfg.use_docker:
        return [
            "docker", "run", "--rm", "--gpus", "all",
            "-v", f"{workdir}:/work",
            cfg.docker_image_gsplat,
            *inner,
        ]
    return inner


# ---------------------------------------------------------------------------
# 4DGS · temporal Gaussian splatting (v2.1 D2.1)
# ---------------------------------------------------------------------------


def build_gsplat4d_cmd(
    cfg: ExecutorConfig, workdir: Path, *, n_frames: int
) -> list[str]:
    """Build 4DGS training command.

    Uses the ``splatfacto-4d`` variant (Gaussian-Splatting-in-Time /
    Deformable-3DGS-style) — trains N per-frame Gaussian buckets sharing a
    common canonical bank + deformation MLP.

    Data layout expected under ``workdir``:
        workdir/
          frames/
            0000/images/*.jpg
            0001/images/*.jpg
            ...

    We pass ``--n-frames N`` so the trainer allocates temporal buckets.
    """
    inner = [
        "ns-train", "splatfacto-4d",
        "--data", "/work" if cfg.use_docker else str(workdir),
        "--output-dir",
        "/work/gsplat4d_out" if cfg.use_docker else str(workdir / "gsplat4d_out"),
        "--max-num-iterations", "40000",
        "--n-frames", str(n_frames),
    ]
    if cfg.use_docker:
        return [
            "docker", "run", "--rm", "--gpus", "all",
            "-v", f"{workdir}:/work",
            cfg.docker_image_gsplat,
            *inner,
        ]
    return inner


# 4dgs trainer prints two PSNR figures at end:
#   "psnr: 27.4"  (spatial, same as 3dgs)
#   "psnr_temporal: 24.1"  (held-out temporal frames)
_GSPLAT4D_PSNR_TEMPORAL = re.compile(
    r"psnr_temporal\s*[:=]\s*([\d.]+)", re.IGNORECASE
)
_GSPLAT4D_N_FRAMES = re.compile(
    r"n_frames\s*[:=]\s*(\d+)", re.IGNORECASE
)


def parse_gsplat4d_stats(stdout: str) -> dict:
    """Extract n_gaussians, psnr, psnr_temporal, n_frames from 4dgs stdout.

    Reuses ``parse_gsplat_stats`` for the shared spatial fields and adds
    the two temporal-only fields.
    """
    base = parse_gsplat_stats(stdout)

    psnr_temporal: Optional[float] = None
    n_frames: Optional[int] = None

    m = _GSPLAT4D_PSNR_TEMPORAL.search(stdout)
    if m:
        try:
            psnr_temporal = float(m.group(1))
        except ValueError:
            pass

    m = _GSPLAT4D_N_FRAMES.search(stdout)
    if m:
        n_frames = int(m.group(1))

    return {
        **base,
        "psnr_temporal": psnr_temporal,
        "n_frames": n_frames,
    }


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


class ColmapExecutor(Executor):
    def __init__(self, cfg: Optional[ExecutorConfig] = None):
        self.cfg = cfg or ExecutorConfig()

    async def run_colmap(self, scene_id: UUID) -> ExecResult:
        workdir = _scene_workdir(self.cfg, scene_id)
        cmd = build_colmap_cmd(self.cfg, workdir)
        log.info("colmap.run scene=%s cmd=%s", scene_id, shlex.join(cmd))
        r = await get_runner().run(cmd, cwd=str(workdir), timeout=self.cfg.colmap_timeout)
        if not r.ok:
            return ExecResult(
                ok=False,
                error=f"colmap exit={r.exit_code}: {r.stderr[-800:]}",
            )
        stats = parse_colmap_stats(r.stdout + "\n" + r.stderr)
        return ExecResult(
            ok=True,
            n_points=stats.get("n_points"),
        )

    async def run_training(self, scene_id: UUID) -> ExecResult:
        # This executor only handles SfM; training is Gsplat's job.
        return ExecResult(ok=False, error="ColmapExecutor does not train; use GsplatExecutor")


class GsplatExecutor(Executor):
    """Runs BOTH colmap and gsplat — production default composite."""

    def __init__(self, cfg: Optional[ExecutorConfig] = None):
        self.cfg = cfg or ExecutorConfig()
        self._colmap = ColmapExecutor(cfg=self.cfg)

    async def run_colmap(self, scene_id: UUID) -> ExecResult:
        return await self._colmap.run_colmap(scene_id)

    async def run_training(self, scene_id: UUID) -> ExecResult:
        workdir = _scene_workdir(self.cfg, scene_id)
        cmd = build_gsplat_cmd(self.cfg, workdir)
        log.info("gsplat.train scene=%s cmd=%s", scene_id, shlex.join(cmd))
        r = await get_runner().run(cmd, cwd=str(workdir), timeout=self.cfg.gsplat_timeout)
        if not r.ok:
            return ExecResult(
                ok=False,
                error=f"gsplat exit={r.exit_code}: {r.stderr[-800:]}",
            )
        stats = parse_gsplat_stats(r.stdout + "\n" + r.stderr)
        return ExecResult(
            ok=True,
            n_gaussians=stats.get("n_gaussians"),
            psnr_train=stats.get("psnr"),
        )


class Gsplat4DExecutor(Executor):
    """4DGS temporal Gaussian splatting executor (v2.1 D2.1).

    Reuses ``ColmapExecutor`` for the SfM stage (each frame's images
    still need calibration), then runs ``splatfacto-4d`` for temporal
    reconstruction. The number of frames is read from ``Scene.n_frames``
    at dispatch time; the executor exposes ``set_frame_count`` so the
    pipeline can inject it without re-instantiating.
    """

    def __init__(self, cfg: Optional[ExecutorConfig] = None):
        self.cfg = cfg or ExecutorConfig()
        self._colmap = ColmapExecutor(cfg=self.cfg)
        self._n_frames: int = 1  # sensible default; caller should override

    def set_frame_count(self, n_frames: int) -> None:
        if n_frames < 1:
            raise ValueError(f"n_frames must be ≥1, got {n_frames}")
        self._n_frames = n_frames

    async def run_colmap(self, scene_id: UUID) -> ExecResult:
        return await self._colmap.run_colmap(scene_id)

    async def run_training(self, scene_id: UUID) -> ExecResult:
        workdir = _scene_workdir(self.cfg, scene_id)
        cmd = build_gsplat4d_cmd(self.cfg, workdir, n_frames=self._n_frames)
        log.info(
            "gsplat4d.train scene=%s n_frames=%d cmd=%s",
            scene_id,
            self._n_frames,
            shlex.join(cmd),
        )
        r = await get_runner().run(
            cmd, cwd=str(workdir), timeout=self.cfg.gsplat_timeout
        )
        if not r.ok:
            return ExecResult(
                ok=False,
                error=f"gsplat4d exit={r.exit_code}: {r.stderr[-800:]}",
            )
        stats = parse_gsplat4d_stats(r.stdout + "\n" + r.stderr)
        return ExecResult(
            ok=True,
            n_gaussians=stats.get("n_gaussians"),
            psnr_train=stats.get("psnr"),
            n_frames=stats.get("n_frames") or self._n_frames,
            psnr_temporal=stats.get("psnr_temporal"),
        )


# ---------------------------------------------------------------------------
# Factory (env-driven default)
# ---------------------------------------------------------------------------


def make_default_executor() -> Executor:
    """Read env and build the appropriate executor.

    SKYMASTER_EXECUTOR = noop | colmap | gsplat | gsplat4d (default noop for dev)
    """
    mode = os.getenv("SKYMASTER_EXECUTOR", "noop").lower()
    if mode == "colmap":
        return ColmapExecutor()
    if mode == "gsplat":
        return GsplatExecutor()
    if mode in ("gsplat4d", "4dgs"):
        return Gsplat4DExecutor()
    from app.services.scene_pipeline import NoOpExecutor
    return NoOpExecutor()
