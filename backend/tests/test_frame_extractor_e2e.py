"""T9.16 · Real-ffmpeg integration test for FrameExtractor.

Unlike test_frame_extractor.py which stubs the CommandRunner, this file
runs the actual ffmpeg / ffprobe binaries on a synthesised tiny mp4 to
prove the pipeline works end-to-end. Skipped when the binaries are not
on PATH so CI stays green on minimal images.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.frame_extractor import (
    FrameExtractionConfig,
    FrameExtractor,
    build_ffprobe_duration_cmd,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg / ffprobe not on PATH",
)


def _make_tiny_mp4(target: Path, seconds: float = 4.0, fps: int = 24) -> None:
    """Synthesise a valid mp4 using ffmpeg's `testsrc` source.

    testsrc renders a moving pattern with a frame counter overlay — every
    frame is distinct, so the extractor can't accidentally dedupe them.
    """
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
        raise RuntimeError(
            f"testsrc synth failed exit={r.returncode}: "
            f"{r.stderr.decode()[-400:]}"
        )
    assert target.stat().st_size > 0, "synthesised mp4 is empty"


# --------------------------------------------------------------------------- #
# ffprobe end-to-end                                                          #
# --------------------------------------------------------------------------- #


async def test_probe_duration_real_ffprobe(tmp_path):
    video = tmp_path / "clip.mp4"
    _make_tiny_mp4(video, seconds=3.0)

    ex = FrameExtractor()
    dur = await ex.probe_duration(video)
    # testsrc target is 3.0s; libx264 encoding rounds to nearest frame,
    # so accept anything in a small tolerance band.
    assert 2.9 <= dur <= 3.1, f"unexpected duration {dur!r}"


async def test_probe_duration_rejects_bad_file(tmp_path):
    junk = tmp_path / "not_a_video.mp4"
    junk.write_bytes(b"this is not mp4")
    ex = FrameExtractor()
    with pytest.raises(RuntimeError):
        await ex.probe_duration(junk)


# --------------------------------------------------------------------------- #
# Full extract flow                                                           #
# --------------------------------------------------------------------------- #


async def test_extract_produces_expected_frames(tmp_path):
    video = tmp_path / "clip.mp4"
    _make_tiny_mp4(video, seconds=4.0, fps=24)

    frames_dir = tmp_path / "frames"
    ex = FrameExtractor(cfg=FrameExtractionConfig(overwrite=True))
    out = await ex.extract(video=video, frames_dir=frames_dir, n_frames=8)

    assert out.ok, f"extract failed: {out.error} / {out.ffmpeg_log_tail}"
    assert out.n_frames == 8

    # Bucket layout: NNNN/images/000000.jpg for NNNN in [0000, 0007]
    for i in range(8):
        p = frames_dir / f"{i:04d}" / "images" / "000000.jpg"
        assert p.is_file(), f"missing frame bucket {p}"
        assert p.stat().st_size > 0, f"empty frame {p}"

    # No stray flat NNNN.jpg files left behind after bucket split
    flat = list(frames_dir.glob("*.jpg"))
    assert flat == [], f"unexpected flat files: {flat}"


async def test_extract_n_frames_2_edge_case(tmp_path):
    """min_frames=2 boundary — a short clip must still yield 2 frames."""
    video = tmp_path / "short.mp4"
    _make_tiny_mp4(video, seconds=2.0, fps=24)

    frames_dir = tmp_path / "frames"
    ex = FrameExtractor(cfg=FrameExtractionConfig(overwrite=True))
    out = await ex.extract(video=video, frames_dir=frames_dir, n_frames=2)
    assert out.ok, out.error
    assert out.n_frames == 2
    assert (frames_dir / "0000" / "images" / "000000.jpg").is_file()
    assert (frames_dir / "0001" / "images" / "000000.jpg").is_file()


async def test_extract_dense_sampling(tmp_path):
    """16 frames from 4s clip = 4 fps — inside libx264's natural fps."""
    video = tmp_path / "clip.mp4"
    _make_tiny_mp4(video, seconds=4.0, fps=24)

    frames_dir = tmp_path / "frames"
    ex = FrameExtractor(cfg=FrameExtractionConfig(overwrite=True))
    out = await ex.extract(video=video, frames_dir=frames_dir, n_frames=16)
    assert out.ok, out.error
    assert out.n_frames == 16
    for i in [0, 5, 10, 15]:
        p = frames_dir / f"{i:04d}" / "images" / "000000.jpg"
        assert p.is_file()


async def test_extract_frames_are_distinct(tmp_path):
    """testsrc renders a frame counter — each extracted frame's bytes
    must differ from every other, proving we're not just grabbing frame 0
    N times."""
    video = tmp_path / "clip.mp4"
    _make_tiny_mp4(video, seconds=4.0, fps=24)

    frames_dir = tmp_path / "frames"
    ex = FrameExtractor(cfg=FrameExtractionConfig(overwrite=True))
    out = await ex.extract(video=video, frames_dir=frames_dir, n_frames=4)
    assert out.ok
    hashes = set()
    for i in range(4):
        p = frames_dir / f"{i:04d}" / "images" / "000000.jpg"
        hashes.add(p.read_bytes())
    assert len(hashes) == 4, "extracted frames must all differ"


async def test_extract_missing_file_short_circuits(tmp_path):
    ex = FrameExtractor()
    out = await ex.extract(
        video=tmp_path / "no_such_file.mp4",
        frames_dir=tmp_path / "out",
        n_frames=4,
    )
    assert not out.ok
    assert "not found" in out.error


async def test_extract_bad_video_ffprobe_error(tmp_path):
    """A file with .mp4 extension but junk contents should surface a
    clear ffprobe error, not an uncaught exception."""
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"\x00" * 100)
    ex = FrameExtractor()
    out = await ex.extract(
        video=junk,
        frames_dir=tmp_path / "out",
        n_frames=4,
    )
    assert not out.ok
    assert "ffprobe" in out.error.lower()


async def test_extract_overwrite_true_wipes_prior_run(tmp_path):
    """Second extract with overwrite=True must clean out stale files."""
    video = tmp_path / "clip.mp4"
    _make_tiny_mp4(video, seconds=3.0)
    frames_dir = tmp_path / "frames"

    ex = FrameExtractor(cfg=FrameExtractionConfig(overwrite=True))
    out1 = await ex.extract(video=video, frames_dir=frames_dir, n_frames=4)
    assert out1.ok

    # Seed a stale file that a second run should not preserve.
    stale = frames_dir / "stale_marker.txt"
    stale.write_text("must be gone")

    out2 = await ex.extract(video=video, frames_dir=frames_dir, n_frames=4)
    assert out2.ok
    assert not stale.exists()
    # And the fresh bucket layout is present
    assert (frames_dir / "0000" / "images" / "000000.jpg").is_file()
