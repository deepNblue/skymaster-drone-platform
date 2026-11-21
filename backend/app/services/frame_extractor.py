"""Frame extractor · v2.1 D2.2 (T9.13)
====================================

For 4DGS scenes the ingestion step takes a source video (or an ordered
image sequence) and produces N evenly-spaced frames laid out as::

    workdir/
      frames/
        0000/images/000000.jpg
        0001/images/000000.jpg
        ...

Each ``frames/NNNN/`` sub-directory then feeds one temporal Gaussian
bucket in :class:`Gsplat4DExecutor`.

Why a dedicated module?
-----------------------
* The whole thing has to be **async-safe** — the FastAPI request handler
  runs in an event loop and must not block on ffmpeg for minutes.
* Extraction is CPU/IO heavy → we spawn ffmpeg as an *external process*
  through the same :class:`CommandRunner` abstraction used by the SfM /
  training executors, so unit tests can stub it out.
* We validate frame count *before* touching ffmpeg — sanity guardrails
  applied here mean the executor / API layer stays clean.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.services.scene_executors import CommandRunner, get_runner

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config & result types                                                       #
# ---------------------------------------------------------------------------


@dataclass
class FrameExtractionConfig:
    """Runtime knobs for the extractor.

    * ``min_frames`` / ``max_frames``: hard bounds; requests outside
      this range raise ``ValueError`` at plan-time (before ffmpeg runs).
    * ``ffmpeg_bin``: overrideable for tests / containers with a
      non-standard ffmpeg path.
    * ``timeout_s``: kills ffmpeg if it exceeds this wall-clock budget.
    * ``jpg_quality``: mjpeg quality; 2 is near-lossless, 5 is a good
      balance for photogrammetry. Higher = smaller / lossier.
    """

    min_frames: int = 2
    max_frames: int = 512
    ffmpeg_bin: str = "ffmpeg"
    timeout_s: float = 900.0  # 15 min hard cap
    jpg_quality: int = 3
    # Force overwrite of pre-existing frames/ folder.
    overwrite: bool = False


@dataclass
class FrameExtractionResult:
    """Outcome of one extraction run."""

    ok: bool
    n_frames: int  # frames actually produced (0 on failure)
    frames_dir: Path
    error: Optional[str] = None
    # Raw ffmpeg log tail — useful for surfacing why a video was rejected.
    ffmpeg_log_tail: str = ""


# ---------------------------------------------------------------------------
# Command building                                                            #
# ---------------------------------------------------------------------------


def build_ffmpeg_extract_cmd(
    video: Path,
    frames_dir: Path,
    n_frames: int,
    duration_seconds: float,
    cfg: FrameExtractionConfig,
) -> list[str]:
    """Build a single ffmpeg command that samples N frames uniformly.

    We use ``-vf fps=N/D`` where D is video duration, producing exactly
    N frames evenly distributed across the clip. This is more reliable
    than counting on ``-frames:v N`` alone, which biases toward the
    start of the file when the video's fps > N.

    Output pattern uses zero-padded 4-digit directories so lexicographic
    ordering equals temporal ordering::

        frames_dir/0000/images/000000.jpg
        frames_dir/0001/images/000000.jpg
        ...

    Frame indexing goes 0..N-1, and each bucket contains exactly one
    frame (the trainer treats each sub-dir as a *view* at a single
    time step).
    """
    if duration_seconds <= 0:
        raise ValueError(
            f"duration_seconds must be > 0, got {duration_seconds!r}"
        )
    if n_frames < cfg.min_frames or n_frames > cfg.max_frames:
        raise ValueError(
            f"n_frames must be in [{cfg.min_frames},{cfg.max_frames}], "
            f"got {n_frames}"
        )

    # Compute the target fps so that N frames span the whole clip.
    # duration_seconds may include a small ffprobe rounding error → we
    # over-request by 0.5% and let ffmpeg's frame-selection stop after
    # N frames via -frames:v.
    target_fps = float(n_frames) / duration_seconds

    # Output: frames_dir/%04d/images/000000.jpg
    # ffmpeg emits sequentially into one dir when using %04d in the
    # filename, so we lay it out as `%04d.jpg` first and then a small
    # post-step will move each into its own sub-dir. Doing the
    # sub-dir split inside the extraction step keeps the pipeline
    # atomic — on failure we can wipe frames_dir and retry.
    output = str(frames_dir / "%04d.jpg")

    return [
        cfg.ffmpeg_bin,
        "-y" if cfg.overwrite else "-n",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(video),
        "-vf", f"fps={target_fps:.6f}",
        "-frames:v", str(n_frames),
        "-q:v", str(cfg.jpg_quality),
        output,
    ]


def build_ffprobe_duration_cmd(
    video: Path, ffprobe_bin: str = "ffprobe"
) -> list[str]:
    """Get the video's duration in seconds (float, plain text output)."""
    return [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]


# ---------------------------------------------------------------------------
# Post-extraction sub-dir splitter                                            #
# ---------------------------------------------------------------------------


def split_frames_into_buckets(frames_dir: Path, n_frames: int) -> int:
    """Move flat ``NNNN.jpg`` files into ``NNNN/images/000000.jpg``.

    Returns the actual number of frames laid out. On mismatch (ffmpeg
    produced fewer files than requested — usually a truncated / corrupt
    video) we return whatever we successfully placed.
    """
    placed = 0
    for i in range(n_frames):
        src = frames_dir / f"{i + 1:04d}.jpg"  # ffmpeg %04d starts at 1
        if not src.exists():
            break
        bucket = frames_dir / f"{i:04d}" / "images"
        bucket.mkdir(parents=True, exist_ok=True)
        dst = bucket / "000000.jpg"
        src.replace(dst)
        placed += 1
    return placed


# ---------------------------------------------------------------------------
# The extractor                                                               #
# ---------------------------------------------------------------------------


class FrameExtractor:
    """Async orchestrator for video → frame-buckets extraction.

    Typical usage in the ingest pipeline::

        ex = FrameExtractor()
        out = await ex.extract(
            video=Path("scene_x/source_video.mp4"),
            frames_dir=Path("scene_x/frames"),
            n_frames=16,
        )
        if not out.ok:
            await transition(db, scene, "failed",
                             error_msg=out.error or "frame extract failed")
    """

    def __init__(
        self,
        cfg: Optional[FrameExtractionConfig] = None,
        runner: Optional[CommandRunner] = None,
    ):
        self.cfg = cfg or FrameExtractionConfig()
        # `runner` is optional for tests; production uses the same
        # SubprocessRunner as the training executors.
        self._runner_override = runner

    def _runner(self) -> CommandRunner:
        return self._runner_override or get_runner()

    async def probe_duration(self, video: Path) -> float:
        cmd = build_ffprobe_duration_cmd(video)
        r = await self._runner().run(
            cmd, cwd=str(video.parent), timeout=30.0
        )
        if not r.ok:
            raise RuntimeError(
                f"ffprobe exit={r.exit_code}: {r.stderr[-400:]}"
            )
        try:
            return float(r.stdout.strip())
        except ValueError as e:
            raise RuntimeError(
                f"ffprobe returned non-float duration: {r.stdout!r}"
            ) from e

    async def extract(
        self,
        video: Path,
        frames_dir: Path,
        n_frames: int,
        *,
        duration_seconds: Optional[float] = None,
    ) -> FrameExtractionResult:
        # 1) Sanity checks
        if not video.exists():
            return FrameExtractionResult(
                ok=False,
                n_frames=0,
                frames_dir=frames_dir,
                error=f"video not found: {video}",
            )
        if n_frames < self.cfg.min_frames or n_frames > self.cfg.max_frames:
            return FrameExtractionResult(
                ok=False,
                n_frames=0,
                frames_dir=frames_dir,
                error=(
                    f"n_frames must be in [{self.cfg.min_frames},"
                    f"{self.cfg.max_frames}], got {n_frames}"
                ),
            )

        # 2) Duration (probe if caller didn't supply — saves one ffprobe).
        if duration_seconds is None:
            try:
                duration_seconds = await self.probe_duration(video)
            except Exception as e:
                return FrameExtractionResult(
                    ok=False,
                    n_frames=0,
                    frames_dir=frames_dir,
                    error=f"ffprobe failed: {e}",
                )
        if duration_seconds <= 0:
            return FrameExtractionResult(
                ok=False,
                n_frames=0,
                frames_dir=frames_dir,
                error=f"invalid duration_seconds={duration_seconds}",
            )

        # 3) Prepare frames_dir
        if frames_dir.exists() and self.cfg.overwrite:
            # Clean out any prior content but keep the dir.
            for p in frames_dir.iterdir():
                if p.is_dir():
                    for c in p.rglob("*"):
                        if c.is_file():
                            c.unlink()
                    # rmdir walks depth-first
                    for c in sorted(p.rglob("*"), reverse=True):
                        if c.is_dir():
                            c.rmdir()
                    p.rmdir()
                else:
                    p.unlink()
        frames_dir.mkdir(parents=True, exist_ok=True)

        # 4) Extract
        cmd = build_ffmpeg_extract_cmd(
            video=video,
            frames_dir=frames_dir,
            n_frames=n_frames,
            duration_seconds=duration_seconds,
            cfg=self.cfg,
        )
        log.info(
            "frame_extractor.extract video=%s n_frames=%d cmd=%s",
            video,
            n_frames,
            shlex.join(cmd),
        )
        r = await self._runner().run(
            cmd, cwd=str(video.parent), timeout=self.cfg.timeout_s
        )
        if not r.ok:
            return FrameExtractionResult(
                ok=False,
                n_frames=0,
                frames_dir=frames_dir,
                error=f"ffmpeg exit={r.exit_code}",
                ffmpeg_log_tail=r.stderr[-800:],
            )

        # 5) Split flat NNNN.jpg into bucketed NNNN/images/000000.jpg
        placed = split_frames_into_buckets(frames_dir, n_frames)
        if placed < n_frames:
            return FrameExtractionResult(
                ok=False,
                n_frames=placed,
                frames_dir=frames_dir,
                error=(
                    f"ffmpeg only produced {placed}/{n_frames} frames "
                    f"(possibly truncated/corrupt video)"
                ),
                ffmpeg_log_tail=r.stderr[-800:],
            )
        return FrameExtractionResult(
            ok=True,
            n_frames=placed,
            frames_dir=frames_dir,
            ffmpeg_log_tail=r.stderr[-400:] if r.stderr else "",
        )
