"""Scene training-artifact export & download — v2.1 T1.3.

After GsplatExecutor completes training, we want to:

1. **Register** the generated ``.ply`` / ``.splat`` files as ``SceneAsset``
   rows so they show up in the scene's asset list.
2. **Serve** those artifacts back to authenticated users so a lawyer /
   surveyor / gov contact can pull them into a desktop viewer (Postshot,
   SuperSplat, Nerfstudio viewer, …).

Endpoints
---------

* ``POST /scenes/{sid}/artifacts/register``   — attach a produced ``.ply``
                                                 to the scene (called by
                                                 the worker or manually)
* ``GET  /scenes/{sid}/artifacts``             — list downloadable artifacts
* ``GET  /scenes/{sid}/assets/{aid}/download`` — stream a single asset
* ``GET  /scenes/{sid}/artifacts/manifest.json`` — JSON manifest (viewer bootstrap)

Security
--------

* Downloads require auth AND the same scene-read policy as ``GET /scenes/{id}``.
* Streams from the storage backend (``open_read``) — never expose raw paths.
* File-name in Content-Disposition is percent-encoded per RFC 6266.
"""
from __future__ import annotations

import mimetypes
import urllib.parse
from pathlib import Path
from typing import Iterable, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.scene import SCENE_ASSET_KINDS, Scene, SceneAsset
from app.models.user import User
from app.services import object_storage as store
from app.services.object_storage import ObjectRef

from app.api.v1.scenes import _authz_read, _authz_write, _load_with_assets


router = APIRouter(prefix="/scenes/{scene_id}", tags=["scenes-artifacts"])


# Which kinds count as "downloadable trained artifacts" (vs source data).
ARTIFACT_KINDS: tuple[str, ...] = ("gsplat_ply", "gsplat_ckpt", "colmap_sparse", "preview_thumb")


# ---------- schemas --------------------------------------------------------


class ArtifactRegister(BaseModel):
    kind: str = Field(..., description=f"one of {list(SCENE_ASSET_KINDS)}")
    filename: str = Field(..., min_length=1, max_length=255)
    sha256_hex: str = Field(..., min_length=64, max_length=64,
                            pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: int = Field(..., ge=0)
    storage_path: str = Field(..., min_length=1, max_length=1024)


class ArtifactOut(BaseModel):
    id: UUID
    kind: str
    filename: str
    size_bytes: Optional[int]
    sha256_hex: Optional[str]
    download_url: str

    class Config:
        from_attributes = True


class ArtifactList(BaseModel):
    scene_id: UUID
    total: int
    artifacts: list[ArtifactOut]


class ArtifactManifest(BaseModel):
    scene_id: UUID
    scene_name: str
    status: str
    n_gaussians: Optional[int]
    psnr_train: Optional[float]
    generated_at: Optional[str]  # scene.updated_at ISO
    artifacts: list[ArtifactOut]


# ---------- helpers --------------------------------------------------------


def _guess_content_type(filename: str) -> str:
    # PLY files aren't in the default mimetypes db.
    lower = filename.lower()
    if lower.endswith(".ply"):
        return "application/octet-stream"  # Postshot/SuperSplat handle as binary
    if lower.endswith(".splat"):
        return "application/octet-stream"
    if lower.endswith(".zip"):
        return "application/zip"
    guess, _ = mimetypes.guess_type(filename)
    return guess or "application/octet-stream"


def _rfc6266_disposition(filename: str) -> str:
    """Build a ``Content-Disposition`` value safe for Unicode filenames.

    RFC 6266 + RFC 5987: use ``filename*=UTF-8''<pct-encoded>``.
    """
    # Sanitize path separators + control chars so filename can't smuggle in newlines/nulls.
    safe = filename.replace("/", "_").replace("\\", "_")
    safe = safe.replace("\r", "").replace("\n", "").replace("\x00", "_")
    ascii_fallback = safe.encode("ascii", "replace").decode("ascii").replace("?", "_")
    pct = urllib.parse.quote(safe, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{pct}"


def _download_url(scene_id: UUID, asset_id: UUID) -> str:
    return f"/api/v1/scenes/{scene_id}/assets/{asset_id}/download"


def _asset_to_artifact(scene_id: UUID, a: SceneAsset) -> ArtifactOut:
    return ArtifactOut(
        id=a.id,
        kind=a.kind,
        filename=a.filename,
        size_bytes=a.size_bytes,
        sha256_hex=a.sha256_hex,
        download_url=_download_url(scene_id, a.id),
    )


def _filter_artifacts(assets: Iterable[SceneAsset]) -> list[SceneAsset]:
    return [a for a in assets if a.kind in ARTIFACT_KINDS]


async def _load_asset_or_404(
    db: AsyncSession, scene_id: UUID, asset_id: UUID
) -> SceneAsset:
    stmt = select(SceneAsset).where(
        SceneAsset.id == asset_id, SceneAsset.scene_id == scene_id
    )
    asset = (await db.execute(stmt)).scalar_one_or_none()
    if asset is None:
        raise HTTPException(404, "asset not found in this scene")
    return asset


# ---------- endpoints ------------------------------------------------------


@router.post("/artifacts/register", response_model=ArtifactOut, status_code=201)
async def register_artifact(
    scene_id: UUID,
    body: ArtifactRegister,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ArtifactOut:
    """Attach an artifact that already exists in object_storage to a scene.

    Callers (worker or admin) provide the CAS ``storage_path`` returned by
    ``object_storage.assemble()``. We don't re-hash here; we trust the
    worker's declaration (belt+braces integrity is done at CAS layer).
    """
    if body.kind not in SCENE_ASSET_KINDS:
        raise HTTPException(400, f"unknown kind {body.kind!r}")
    scene = await _load_with_assets(db, scene_id)
    _authz_write(scene, user)

    asset = SceneAsset(
        scene_id=scene.id,
        kind=body.kind,
        filename=body.filename,
        storage_path=body.storage_path,
        size_bytes=body.size_bytes,
        sha256_hex=body.sha256_hex.lower(),
        uploaded_by=user.id,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return _asset_to_artifact(scene.id, asset)


@router.get("/artifacts", response_model=ArtifactList)
async def list_artifacts(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ArtifactList:
    scene = await _load_with_assets(db, scene_id)
    _authz_read(scene, user)
    arts = _filter_artifacts(scene.assets or [])
    return ArtifactList(
        scene_id=scene.id,
        total=len(arts),
        artifacts=[_asset_to_artifact(scene.id, a) for a in arts],
    )


@router.get("/artifacts/manifest.json", response_model=ArtifactManifest)
async def artifacts_manifest(
    scene_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ArtifactManifest:
    """Bootstrap payload for 3D viewers to load a scene."""
    scene = await _load_with_assets(db, scene_id)
    _authz_read(scene, user)
    arts = _filter_artifacts(scene.assets or [])
    generated_at = scene.updated_at.isoformat() if scene.updated_at else None
    return ArtifactManifest(
        scene_id=scene.id,
        scene_name=scene.name,
        status=scene.status,
        n_gaussians=scene.n_gaussians,
        psnr_train=scene.psnr_train,
        generated_at=generated_at,
        artifacts=[_asset_to_artifact(scene.id, a) for a in arts],
    )


@router.get("/assets/{asset_id}/download")
async def download_asset(
    scene_id: UUID,
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    scene = await _load_with_assets(db, scene_id)
    _authz_read(scene, user)
    asset = await _load_asset_or_404(db, scene_id, asset_id)

    # Reconstruct an ObjectRef from the row.
    if not asset.storage_path or not Path(asset.storage_path).exists():
        raise HTTPException(410, "asset file missing on storage")

    ref = ObjectRef(
        sha256_hex=asset.sha256_hex or "",
        size_bytes=asset.size_bytes or 0,
        storage_path=asset.storage_path,
    )
    fh = store.get_storage().open_read(ref)

    def _iter(chunk_size: int = 1 << 20):
        try:
            while True:
                buf = fh.read(chunk_size)
                if not buf:
                    break
                yield buf
        finally:
            fh.close()

    headers = {
        "Content-Disposition": _rfc6266_disposition(asset.filename),
        "X-Sha256": asset.sha256_hex or "",
    }
    if asset.size_bytes is not None:
        headers["Content-Length"] = str(asset.size_bytes)

    return StreamingResponse(
        _iter(),
        media_type=_guess_content_type(asset.filename),
        headers=headers,
    )
