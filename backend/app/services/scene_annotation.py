"""D2.2 · Scene annotation service — CRUD + queries + geometry helpers."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scene_annotation import (
    SceneAnnotation,
    SceneAnnotationReply,
    VALID_GEOM_KINDS,
    VALID_SEVERITIES,
)


class AnnotationError(Exception):
    """Domain error, mapped to HTTP 400/404 at REST layer."""


# ---------------------------------------------------------------------------
# Geometry helpers (local ENU frame, metric).
# ---------------------------------------------------------------------------

def _validate_vertices(kind: str, verts: list[Any]) -> None:
    if not isinstance(verts, list) or not verts:
        raise AnnotationError("geom_vertices must be a non-empty list")
    for i, v in enumerate(verts):
        if not (isinstance(v, list) and len(v) == 3
                and all(isinstance(c, (int, float)) for c in v)):
            raise AnnotationError(
                f"geom_vertices[{i}] must be [x, y, z] numeric"
            )
    if kind == "point" and len(verts) != 1:
        raise AnnotationError("point annotation requires exactly 1 vertex")
    if kind == "line" and len(verts) < 2:
        raise AnnotationError("line annotation requires ≥2 vertices")
    if kind == "polygon" and len(verts) < 3:
        raise AnnotationError("polygon annotation requires ≥3 vertices")
    if kind == "volume" and len(verts) < 3:
        raise AnnotationError("volume annotation requires ≥3 base vertices")


def line_length_m(verts: list[list[float]]) -> float:
    """Sum of segment lengths for a polyline in local metric frame."""
    total = 0.0
    for a, b in zip(verts, verts[1:]):
        total += math.sqrt(
            (a[0] - b[0]) ** 2
            + (a[1] - b[1]) ** 2
            + (a[2] - b[2]) ** 2
        )
    return total


def polygon_area_m2(verts: list[list[float]]) -> float:
    """Planar polygon area (XY projection) via shoelace."""
    if len(verts) < 3:
        return 0.0
    s = 0.0
    for a, b in zip(verts, verts[1:] + [verts[0]]):
        s += a[0] * b[1] - b[0] * a[1]
    return abs(s) / 2.0


def summarize_geometry(kind: str, verts: list[list[float]]) -> dict[str, Any]:
    """Compute display summary (length / area / height / volume)."""
    out: dict[str, Any] = {"kind": kind, "n_vertices": len(verts)}
    if kind == "line":
        out["length_m"] = line_length_m(verts)
    elif kind == "polygon":
        out["perimeter_m"] = line_length_m(verts + [verts[0]])
        out["area_m2"] = polygon_area_m2(verts)
    elif kind == "volume":
        out["footprint_area_m2"] = polygon_area_m2(verts)
    return out


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def create_annotation(
    db: AsyncSession,
    *,
    scene_id: uuid.UUID,
    org_id: uuid.UUID,
    author_id: uuid.UUID,
    geom_kind: str,
    geom_vertices: list[Any],
    label: str,
    description: str | None = None,
    color: str = "#22d3ee",
    severity: str = "info",
    frame_index: int | None = None,
    layer: str = "default",
    meta: dict[str, Any] | None = None,
) -> SceneAnnotation:
    if geom_kind not in VALID_GEOM_KINDS:
        raise AnnotationError(f"invalid geom_kind: {geom_kind}")
    if severity not in VALID_SEVERITIES:
        raise AnnotationError(f"invalid severity: {severity}")
    label = label.strip()
    if not label:
        raise AnnotationError("label is required")
    _validate_vertices(geom_kind, geom_vertices)
    if frame_index is not None and frame_index < 0:
        raise AnnotationError("frame_index must be >= 0 (or NULL for static)")

    row = SceneAnnotation(
        scene_id=scene_id,
        org_id=org_id,
        author_id=author_id,
        geom_kind=geom_kind,
        geom_vertices=geom_vertices,
        color=color,
        label=label,
        description=description,
        severity=severity,
        frame_index=frame_index,
        layer=layer.strip() or "default",
        meta=meta or {},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_annotation(
    db: AsyncSession, *, org_id: uuid.UUID, ann_id: uuid.UUID,
) -> SceneAnnotation | None:
    q = select(SceneAnnotation).where(
        SceneAnnotation.id == ann_id,
        SceneAnnotation.org_id == org_id,
    )
    return (await db.execute(q)).scalar_one_or_none()


async def list_by_scene(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    scene_id: uuid.UUID,
    layer: str | None = None,
    severity: str | None = None,
    only_unresolved: bool = False,
    frame_index: int | None = None,
) -> list[SceneAnnotation]:
    conds = [
        SceneAnnotation.org_id == org_id,
        SceneAnnotation.scene_id == scene_id,
    ]
    if layer:
        conds.append(SceneAnnotation.layer == layer)
    if severity:
        if severity not in VALID_SEVERITIES:
            raise AnnotationError(f"invalid severity filter: {severity}")
        conds.append(SceneAnnotation.severity == severity)
    if only_unresolved:
        conds.append(SceneAnnotation.resolved.is_(False))
    if frame_index is not None:
        conds.append(
            (SceneAnnotation.frame_index == frame_index)
            | SceneAnnotation.frame_index.is_(None)
        )
    q = select(SceneAnnotation).where(and_(*conds)).order_by(
        SceneAnnotation.created_at.desc(),
    )
    return list((await db.execute(q)).scalars().all())


async def update_annotation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    ann_id: uuid.UUID,
    label: str | None = None,
    description: str | None = None,
    color: str | None = None,
    severity: str | None = None,
    resolved: bool | None = None,
    layer: str | None = None,
    meta: dict[str, Any] | None = None,
) -> SceneAnnotation:
    row = await get_annotation(db, org_id=org_id, ann_id=ann_id)
    if row is None:
        raise AnnotationError("annotation not found")
    if label is not None:
        row.label = label.strip() or row.label
    if description is not None:
        row.description = description
    if color is not None:
        row.color = color
    if severity is not None:
        if severity not in VALID_SEVERITIES:
            raise AnnotationError(f"invalid severity: {severity}")
        row.severity = severity
    if resolved is not None:
        row.resolved = resolved
    if layer is not None:
        row.layer = layer.strip() or row.layer
    if meta is not None:
        row.meta = meta
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_annotation(
    db: AsyncSession, *, org_id: uuid.UUID, ann_id: uuid.UUID,
) -> bool:
    row = await get_annotation(db, org_id=org_id, ann_id=ann_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------

async def create_reply(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    annotation_id: uuid.UUID,
    author_id: uuid.UUID,
    body: str,
) -> SceneAnnotationReply:
    parent = await get_annotation(
        db, org_id=org_id, ann_id=annotation_id,
    )
    if parent is None:
        raise AnnotationError("annotation not found")
    if not body.strip():
        raise AnnotationError("reply body is required")
    row = SceneAnnotationReply(
        annotation_id=annotation_id,
        author_id=author_id,
        body=body.strip(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_replies(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    annotation_id: uuid.UUID,
) -> list[SceneAnnotationReply]:
    # verify parent visibility first
    parent = await get_annotation(
        db, org_id=org_id, ann_id=annotation_id,
    )
    if parent is None:
        raise AnnotationError("annotation not found")
    q = select(SceneAnnotationReply).where(
        SceneAnnotationReply.annotation_id == annotation_id,
    ).order_by(SceneAnnotationReply.created_at.asc())
    return list((await db.execute(q)).scalars().all())


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

async def stats_by_scene(
    db: AsyncSession, *, org_id: uuid.UUID, scene_id: uuid.UUID,
) -> dict[str, Any]:
    """Roll-up counts by severity + resolved for a scene."""
    q = select(
        SceneAnnotation.severity,
        SceneAnnotation.resolved,
        func.count(SceneAnnotation.id),
    ).where(
        SceneAnnotation.scene_id == scene_id,
        SceneAnnotation.org_id == org_id,
    ).group_by(SceneAnnotation.severity, SceneAnnotation.resolved)
    rows = (await db.execute(q)).all()

    by_sev: dict[str, int] = {s: 0 for s in VALID_SEVERITIES}
    unresolved = 0
    total = 0
    for sev, resolved, cnt in rows:
        by_sev[sev] = by_sev.get(sev, 0) + int(cnt)
        total += int(cnt)
        if not resolved:
            unresolved += int(cnt)
    return {
        "scene_id": str(scene_id),
        "total": total,
        "unresolved": unresolved,
        "by_severity": by_sev,
    }
