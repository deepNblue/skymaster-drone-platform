"""D3.3 · 4DGS frame diff / change detection service.

Given a 4DGS scene with per-frame metadata (D3.1), produce a diff
report between two frames or between adjacent frames across the
whole timeline.

Signals used:
    * PSNR drop (reconstruction quality degradation)
    * Lighting transitions (day->night etc.)
    * Keyframe boundaries (major scene changes)
    * captured_at gaps (temporal discontinuity)

Output = list of ``ChangePoint`` dicts sorted by frame_index, each
with severity (info/low/medium/high/critical) so the frontend can
render them on the timeline as markers.

Pure functions on top of scene_frame service. No new tables.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.scene_frame import (
    FrameError, _load_scene, list_frames,
)


# Thresholds — tuned for reasonableness, override via kwargs.
DEFAULT_PSNR_DROP_DB = 3.0          # drop >=3 dB flagged
DEFAULT_PSNR_CRITICAL_DB = 6.0      # drop >=6 dB critical
DEFAULT_TIME_GAP_S = 60.0           # captured_at gap >=60 s flagged
DEFAULT_TIME_GAP_CRITICAL_S = 300.0  # >=5 min critical


def _severity_from_psnr(delta: float, warn: float, crit: float) -> str:
    """delta = prev_psnr - curr_psnr (positive means drop)."""
    if delta >= crit:
        return "critical"
    if delta >= warn * 1.5:
        return "high"
    if delta >= warn:
        return "medium"
    return "low"


def compute_diff_between(
    frame_a: dict[str, Any], frame_b: dict[str, Any],
    *,
    psnr_warn: float = DEFAULT_PSNR_DROP_DB,
    psnr_crit: float = DEFAULT_PSNR_CRITICAL_DB,
    time_warn_s: float = DEFAULT_TIME_GAP_S,
    time_crit_s: float = DEFAULT_TIME_GAP_CRITICAL_S,
) -> dict[str, Any]:
    """Pure function — no DB. Called by REST and by tests directly.

    Returns a change-point dict, always with the same schema so the
    frontend can render uniformly. ``reasons`` explains why.
    """
    reasons: list[str] = []
    severity = "info"

    # PSNR drop.
    p_a = frame_a.get("psnr_frame")
    p_b = frame_b.get("psnr_frame")
    psnr_delta: float | None = None
    if p_a is not None and p_b is not None:
        psnr_delta = float(p_a) - float(p_b)
        if psnr_delta >= psnr_warn:
            sev = _severity_from_psnr(psnr_delta, psnr_warn, psnr_crit)
            severity = _worst(severity, sev)
            reasons.append(
                f"PSNR 下降 {psnr_delta:.2f} dB (阈值 {psnr_warn} dB)"
            )

    # Lighting transition.
    l_a = frame_a.get("lighting")
    l_b = frame_b.get("lighting")
    if l_a and l_b and l_a != l_b:
        severity = _worst(severity, "medium")
        reasons.append(f"光照 {l_a} → {l_b}")

    # Keyframe boundary (a→b crosses a keyframe means recon changed).
    if frame_a.get("is_keyframe") or frame_b.get("is_keyframe"):
        severity = _worst(severity, "low")
        reasons.append("跨关键帧")

    # Temporal gap.
    t_a = frame_a.get("captured_at")
    t_b = frame_b.get("captured_at")
    gap_s: float | None = None
    if t_a and t_b:
        try:
            gap_s = abs((t_b - t_a).total_seconds())
            if gap_s >= time_crit_s:
                severity = _worst(severity, "critical")
                reasons.append(
                    f"采集时间间隔 {gap_s:.0f}s (临界 {time_crit_s:.0f}s)"
                )
            elif gap_s >= time_warn_s:
                severity = _worst(severity, "high")
                reasons.append(
                    f"采集时间间隔 {gap_s:.0f}s (告警 {time_warn_s:.0f}s)"
                )
        except (AttributeError, TypeError):
            pass  # non-datetime, skip

    return {
        "from_index": frame_a.get("frame_index"),
        "to_index": frame_b.get("frame_index"),
        "severity": severity,
        "reasons": reasons,
        "psnr_delta": psnr_delta,
        "time_gap_s": gap_s,
        "lighting_from": l_a,
        "lighting_to": l_b,
    }


_SEV_ORDER = {
    "info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4,
}


def _worst(a: str, b: str) -> str:
    return a if _SEV_ORDER.get(a, 0) >= _SEV_ORDER.get(b, 0) else b


async def diff_between_indices(
    db: AsyncSession, *,
    scene_id: uuid.UUID, org_id: uuid.UUID,
    a: int, b: int,
    **thresholds: float,
) -> dict[str, Any]:
    """Compare two specific frames in a 4DGS scene."""
    await _load_scene(db, scene_id=scene_id, org_id=org_id)
    frames = await list_frames(
        db, scene_id=scene_id, org_id=org_id,
    )
    idx = {f.frame_index: f for f in frames}
    if a not in idx or b not in idx:
        raise FrameError(
            f"frame not found: a={a} b={b}",
        )
    return compute_diff_between(
        _row_to_dict(idx[a]), _row_to_dict(idx[b]), **thresholds,
    )


async def timeline_change_report(
    db: AsyncSession, *,
    scene_id: uuid.UUID, org_id: uuid.UUID,
    min_severity: str = "low",
    **thresholds: float,
) -> dict[str, Any]:
    """Walk the timeline pair-wise and collect all change points."""
    await _load_scene(db, scene_id=scene_id, org_id=org_id)
    frames = await list_frames(
        db, scene_id=scene_id, org_id=org_id,
    )
    if len(frames) < 2:
        return {
            "scene_id": str(scene_id),
            "total_frames": len(frames),
            "change_points": [],
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
        }
    threshold = _SEV_ORDER.get(min_severity, 1)
    points: list[dict[str, Any]] = []
    for i in range(1, len(frames)):
        pt = compute_diff_between(
            _row_to_dict(frames[i - 1]),
            _row_to_dict(frames[i]),
            **thresholds,
        )
        if _SEV_ORDER.get(pt["severity"], 0) >= threshold:
            points.append(pt)
    return {
        "scene_id": str(scene_id),
        "total_frames": len(frames),
        "change_points": points,
        "critical_count": sum(
            1 for p in points if p["severity"] == "critical"
        ),
        "high_count": sum(
            1 for p in points if p["severity"] == "high"
        ),
        "medium_count": sum(
            1 for p in points if p["severity"] == "medium"
        ),
    }


def _row_to_dict(r: Any) -> dict[str, Any]:
    return {
        "frame_index": r.frame_index,
        "psnr_frame": r.psnr_frame,
        "lighting": r.lighting,
        "is_keyframe": r.is_keyframe,
        "captured_at": r.captured_at,
    }
