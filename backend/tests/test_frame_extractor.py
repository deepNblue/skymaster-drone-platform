"""Unit tests for the video → 4DGS frame extractor (v2.1 D2.2, T9.13)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.frame_extractor import (
    FrameExtractionConfig,
    FrameExtractionResult,
    FrameExtractor,
    build_ffmpeg_extract_cmd,
    build_ffprobe_duration_cmd,
    split_frames_into_buckets,
)


# --------------------------------------------------------------------- #
# Fake runner                                                            #
# --------------------------------------------------------------------- #


class _FakeRunner:
    """Mimics CommandRunner but returns pre-canned results and records
    the invocations it received."""

    def __init__(self, results: list):
        # results is a list of (ok, stdout, stderr, exit_code) tuples,
        # consumed in FIFO order.
        self.results = list(results)
        self.calls: list[dict] = []

    async def run(self, cmd, cwd, timeout):
        rec = {"cmd": cmd, "cwd": cwd, "timeout": timeout}
        self.calls.append(rec)
        ok, stdout, stderr, exit_code = self.results.pop(0)

        class _R:
            pass

        r = _R()
        r.ok = ok
        r.stdout = stdout
        r.stderr = stderr
        r.exit_code = exit_code
        return r


# --------------------------------------------------------------------- #
# Command building                                                       #
# --------------------------------------------------------------------- #


def test_build_ffmpeg_extract_cmd_basics(tmp_path):
    cfg = FrameExtractionConfig()
    cmd = build_ffmpeg_extract_cmd(
        video=tmp_path / "in.mp4",
        frames_dir=tmp_path / "frames",
        n_frames=8,
        duration_seconds=16.0,
        cfg=cfg,
    )
    # Basic shape
    assert cmd[0] == "ffmpeg"
    assert "-i" in cmd
    assert str(tmp_path / "in.mp4") in cmd
    assert "-frames:v" in cmd
    assert cmd[cmd.index("-frames:v") + 1] == "8"
    # fps = 8 / 16 = 0.5
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("fps=")
    # Must include quality flag
    assert "-q:v" in cmd


def test_build_ffmpeg_extract_cmd_rejects_bad_duration(tmp_path):
    cfg = FrameExtractionConfig()
    with pytest.raises(ValueError):
        build_ffmpeg_extract_cmd(
            video=tmp_path / "in.mp4",
            frames_dir=tmp_path / "frames",
            n_frames=8,
            duration_seconds=0.0,
            cfg=cfg,
        )


def test_build_ffmpeg_extract_cmd_rejects_out_of_bounds_frames(tmp_path):
    cfg = FrameExtractionConfig(min_frames=2, max_frames=100)
    with pytest.raises(ValueError):
        build_ffmpeg_extract_cmd(
            tmp_path / "x.mp4",
            tmp_path / "f",
            n_frames=1,
            duration_seconds=10.0,
            cfg=cfg,
        )
    with pytest.raises(ValueError):
        build_ffmpeg_extract_cmd(
            tmp_path / "x.mp4",
            tmp_path / "f",
            n_frames=200,
            duration_seconds=10.0,
            cfg=cfg,
        )


def test_build_ffprobe_duration_cmd():
    cmd = build_ffprobe_duration_cmd(Path("/tmp/x.mp4"))
    assert cmd[0] == "ffprobe"
    assert "format=duration" in " ".join(cmd)
    assert "/tmp/x.mp4" in cmd


# --------------------------------------------------------------------- #
# split_frames_into_buckets                                              #
# --------------------------------------------------------------------- #


def test_split_frames_into_buckets_layout(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    # Simulate ffmpeg output: flat NNNN.jpg files (1-indexed)
    for i in range(1, 5):
        (frames / f"{i:04d}.jpg").write_bytes(b"jpg" + bytes([i]))
    placed = split_frames_into_buckets(frames, n_frames=4)
    assert placed == 4
    # Layout must be 0000/images/000000.jpg .. 0003/images/000000.jpg
    for i in range(4):
        p = frames / f"{i:04d}" / "images" / "000000.jpg"
        assert p.is_file()
    # Original flat files must be gone
    assert not (frames / "0001.jpg").exists()


def test_split_frames_stops_on_missing_file(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in [1, 2]:  # missing 3
        (frames / f"{i:04d}.jpg").write_bytes(b"jpg")
    # Even if we asked for 4, only 2 exist
    placed = split_frames_into_buckets(frames, n_frames=4)
    assert placed == 2
    assert (frames / "0000" / "images" / "000000.jpg").is_file()
    assert (frames / "0001" / "images" / "000000.jpg").is_file()
    assert not (frames / "0002" / "images" / "000000.jpg").exists()


# --------------------------------------------------------------------- #
# FrameExtractor.extract — full async flow                               #
# --------------------------------------------------------------------- #


async def _touch_frames_after_ffmpeg(frames_dir: Path, n: int):
    """Helper to simulate ffmpeg's output: create N flat jpgs."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (frames_dir / f"{i:04d}.jpg").write_bytes(b"\xff\xd8\xff\xd9")


async def test_extract_happy_path(tmp_path):
    video = tmp_path / "in.mp4"
    video.write_bytes(b"fake video")
    frames_dir = tmp_path / "frames"

    # Runner returns:
    #  1) ffprobe: duration = 16.0
    #  2) ffmpeg: success (but we must ALSO physically place the files —
    #     the runner is stubbed, so simulate ffmpeg's file output first)
    async def _side_effect(cmd, cwd, timeout):  # noqa: ARG001
        class _R:
            pass

        r = _R()
        r.timeout = timeout
        if cmd[0] == "ffprobe":
            r.ok, r.stdout, r.stderr, r.exit_code = True, "16.0\n", "", 0
        else:  # ffmpeg
            await _touch_frames_after_ffmpeg(frames_dir, 8)
            r.ok, r.stdout, r.stderr, r.exit_code = True, "", "", 0
        return r

    class _AsyncRunner:
        async def run(self, cmd, cwd, timeout):
            return await _side_effect(cmd, cwd, timeout)

    ex = FrameExtractor(runner=_AsyncRunner())
    out = await ex.extract(video=video, frames_dir=frames_dir, n_frames=8)
    assert out.ok, out.error
    assert out.n_frames == 8
    # Bucketed layout must exist
    assert (frames_dir / "0000" / "images" / "000000.jpg").is_file()
    assert (frames_dir / "0007" / "images" / "000000.jpg").is_file()


async def test_extract_missing_video(tmp_path):
    ex = FrameExtractor()
    out = await ex.extract(
        video=tmp_path / "nope.mp4",
        frames_dir=tmp_path / "frames",
        n_frames=4,
    )
    assert not out.ok
    assert "not found" in out.error


async def test_extract_ffprobe_fails(tmp_path):
    video = tmp_path / "in.mp4"
    video.write_bytes(b"corrupt")
    runner = _FakeRunner([(False, "", "moov atom not found", 1)])
    ex = FrameExtractor(runner=runner)
    out = await ex.extract(video, tmp_path / "frames", n_frames=4)
    assert not out.ok
    assert "ffprobe failed" in out.error


async def test_extract_ffmpeg_fails(tmp_path):
    video = tmp_path / "in.mp4"
    video.write_bytes(b"vid")
    frames_dir = tmp_path / "frames"
    runner = _FakeRunner(
        [
            (True, "10.0", "", 0),       # ffprobe success
            (False, "", "encoder oom", 137),  # ffmpeg fail
        ]
    )
    ex = FrameExtractor(runner=runner)
    out = await ex.extract(video, frames_dir, n_frames=4)
    assert not out.ok
    assert "exit=137" in out.error
    assert "encoder oom" in out.ffmpeg_log_tail


async def test_extract_truncated_video_only_gets_partial_frames(tmp_path):
    video = tmp_path / "in.mp4"
    video.write_bytes(b"vid")
    frames_dir = tmp_path / "frames"

    async def _side_effect(cmd, cwd, timeout):  # noqa: ARG001
        class _R:
            pass

        r = _R()
        if cmd[0] == "ffprobe":
            r.ok, r.stdout, r.stderr, r.exit_code = True, "5.0", "", 0
        else:
            # Only produce 3 of the requested 8 frames.
            await _touch_frames_after_ffmpeg(frames_dir, 3)
            r.ok, r.stdout, r.stderr, r.exit_code = (
                True,
                "",
                "video ended at 1.9s",
                0,
            )
        return r

    class _R:
        async def run(self, cmd, cwd, timeout):
            return await _side_effect(cmd, cwd, timeout)

    ex = FrameExtractor(runner=_R())
    out = await ex.extract(video, frames_dir, n_frames=8)
    assert not out.ok
    assert out.n_frames == 3
    assert "3/8" in out.error


async def test_extract_bounds_rejected_before_ffmpeg(tmp_path):
    """n_frames out-of-bounds should short-circuit BEFORE spawning ffmpeg."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    runner = _FakeRunner([])  # no results — must not be called
    ex = FrameExtractor(
        cfg=FrameExtractionConfig(min_frames=2, max_frames=10),
        runner=runner,
    )
    out = await ex.extract(video, tmp_path / "f", n_frames=1)
    assert not out.ok
    assert "n_frames must be in" in out.error
    assert runner.calls == []  # zero ffprobe / ffmpeg calls
