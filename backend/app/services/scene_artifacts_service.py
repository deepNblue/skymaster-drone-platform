"""Training-artifact collection & registration — 3DGS backend closure.

After a real executor finishes, produced ``.ply`` / ``.splat`` files sit in
the scene workdir. This module:

1. **collects** them by scanning the output dir (config-driven globs),
2. **imports** each into the content-addressed store (``object_storage``),
3. **registers** a ``SceneAsset`` row so it appears in the artifact list and
   is downloadable via ``GET /scenes/{id}/assets/{aid}/download``.

Design contract
---------------
* No HTTP calls / no user context — the pipeline calls this with a live DB
  session. ``uploaded_by`` is left NULL (system-produced artifact).
* Everything configurable lives in ``config/scene_3dgs.json`` → ``artifacts``.
* Idempotent: re-registering the same sha256 within a scene is a no-op
  (CAS dedups the bytes, and we skip duplicate SceneAsset rows).
* Import failures degrade to a structured result — they never flip a
  successful training into ``failed``; the scene still reaches ``ready``.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scene import Scene, SceneAsset
from app.services import object_storage as store
from app.services.scene_executors import load_scene_config

log = logging.getLogger(__name__)

_CHUNK = 1 << 20  # 1 MiB — same order as the upload path


@dataclass
class RegisterResult:
    registered: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "registered": self.registered,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def _artifact_cfg() -> dict:
    return load_scene_config().get("artifacts", {})


def _kind_for(path: Path, cfg: dict) -> Optional[str]:
    mapping = cfg.get("kind_by_ext", {"ply": "gsplat_ply", "splat": "gsplat_ply"})
    ext = path.suffix.lower().lstrip(".")
    if ext in mapping:
        return str(mapping[ext])
    if cfg.get("include_ckpt") and ext in ("ckpt", "safetensors"):
        return str(cfg.get("ckpt_kind", "gsplat_ckpt"))
    return None


def collect_output_paths(workdir: Path, cfg: Optional[dict] = None) -> list[Path]:
    """Scan ``workdir`` for produced model files using config globs."""
    acfg = cfg if cfg is not None else _artifact_cfg()
    if not acfg.get("auto_register", True):
        return []
    found: dict[str, Path] = {}
    for pattern in acfg.get("output_globs", ["**/*.ply", "**/*.splat"]):
        for p in workdir.glob(pattern):
            if p.is_file() and _kind_for(p, acfg):
                found[str(p.resolve())] = p
    if acfg.get("include_ckpt"):
        for pattern in acfg.get("ckpt_globs", []):
            for p in workdir.glob(pattern):
                if p.is_file() and _kind_for(p, acfg):
                    found[str(p.resolve())] = p
    return sorted(found.values(), key=lambda x: str(x))


def _import_file_into_cas(path: Path, upload_id: str) -> tuple[str, int, str]:
    """Stream a local file into CAS via the standard staging/assemble path."""
    backend = store.get_storage()
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
            backend.stage_chunk(upload_id, total, chunk)
            total += 1
    digest = h.hexdigest()
    ref = backend.assemble(upload_id, digest, total)
    return ref.sha256_hex, ref.size_bytes, ref.storage_path


async def register_produced_artifacts(
    db: AsyncSession,
    scene: Scene,
    paths: list[str | Path],
) -> RegisterResult:
    """Import candidate files into CAS and attach them to ``scene``."""
    result = RegisterResult()
    acfg = _artifact_cfg()
    if not acfg.get("auto_register", True) or not paths:
        return result
    max_bytes = int(acfg.get("max_bytes", 4 * 1024**3))

    existing: set[tuple[str, str]] = set()
    rows = await db.execute(
        select(SceneAsset.kind, SceneAsset.sha256_hex).where(
            SceneAsset.scene_id == scene.id
        )
    )
    for kind, sha in rows.all():
        if sha:
            existing.add((str(kind), str(sha)))

    for raw in paths:
        p = Path(raw)
        name = p.name
        try:
            if not p.is_file():
                result.skipped.append({"filename": name, "reason": "missing"})
                continue
            size = p.stat().st_size
            if size <= 0:
                result.skipped.append({"filename": name, "reason": "empty"})
                continue
            if size > max_bytes:
                result.skipped.append({"filename": name, "reason": "too_large"})
                continue
            kind = _kind_for(p, acfg)
            if not kind:
                result.skipped.append({"filename": name, "reason": "unknown_ext"})
                continue

            tag = hashlib.sha1(f"{scene.id}:{p}".encode()).hexdigest()[:16]
            upload_id = f"trained-{scene.id.hex}-{tag}"
            sha, stored_size, storage_path = await _async_import(
                _import_file_into_cas, p, upload_id
            )
            if (kind, sha) in existing:
                result.skipped.append({"filename": name, "sha256_hex": sha,
                                       "reason": "duplicate"})
                continue

            asset = SceneAsset(
                scene_id=scene.id,
                kind=kind,
                filename=name,
                storage_path=storage_path,
                size_bytes=stored_size,
                sha256_hex=sha,
                uploaded_by=None,
            )
            db.add(asset)
            existing.add((kind, sha))
            result.registered.append({
                "filename": name, "kind": kind,
                "sha256_hex": sha, "size_bytes": stored_size,
            })
            log.info(
                "scene artifact registered scene=%s kind=%s file=%s sha=%s",
                scene.id, kind, name, sha[:12],
            )
        except Exception as exc:  # noqa: BLE001 — never fail a successful training
            result.errors.append({"filename": name, "error": str(exc)[:300]})
            log.warning("artifact registration failed for %s: %s", name, exc)

    if result.registered:
        await db.commit()
    return result


async def _async_import(fn, *args):  # run blocking CAS IO off the event loop
    import asyncio
    return await asyncio.to_thread(fn, *args)
