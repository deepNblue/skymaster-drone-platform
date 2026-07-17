"""Scene chunked upload API — v2.1 T1.1.

Chunked resumable upload for scene assets.

Flow (client side):
    1. POST /scenes/{sid}/uploads       (start; declare filename+sha256+size+chunks)
       ← returns upload_id
    2. PUT  /scenes/{sid}/uploads/{uid}/chunks/{idx}   (binary chunk body)
       ...  (repeat, order-independent, re-runnable = idempotent)
    3. GET  /scenes/{sid}/uploads/{uid}      (poll — returns received chunks list)
    4. POST /scenes/{sid}/uploads/{uid}/complete   (assemble → CAS → SceneAsset row)
       ← returns asset_id + sha256
    5. DELETE /scenes/{sid}/uploads/{uid}    (abort → GC staging)

Deduplication:
    Same sha256 uploaded again → assembly returns the existing CAS entry;
    a new SceneAsset row still gets created so each scene sees the file
    even though the bytes on disk are shared.

Security:
    * Chunk size hard-capped at 32 MiB per PUT so a bad client can't blow RAM.
    * upload_id is a UUID we mint; caller can't forge staging paths.
    * All writes go through LocalFSBackend which validates path components.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.scene import SCENE_ASSET_KINDS, Scene, SceneAsset
from app.models.user import User
from app.services import object_storage as store
from app.services.object_storage import (
    StorageChunkMissing, StorageError, StorageIntegrityError,
)

from app.api.v1.scenes import _authz_write, _load_with_assets  # reuse


router = APIRouter(prefix="/scenes/{scene_id}/uploads", tags=["scenes-upload"])


MAX_CHUNK_BYTES = 32 * 1024 * 1024  # 32 MiB per chunk


# ---------------------------------------------------------------------------
# Per-kind ingest policy · v2.1 T9.15
# ---------------------------------------------------------------------------
# Each SceneAsset kind gets its own upper size bound + allowed filename
# extensions. Enforcing on `POST /uploads` (start_upload) means bad
# clients fail fast — before any bytes hit the wire.

# Absolute size caps (bytes). Chosen to cover realistic mission data
# but bound blast radius on a runaway client.
KIND_MAX_BYTES: dict[str, int] = {
    "source_image":    200 * 1024 * 1024,        # 200 MiB / photo
    "source_video":      8 * 1024 * 1024 * 1024, # 8 GiB / clip
    "colmap_sparse":   500 * 1024 * 1024,        # 500 MiB
    "colmap_dense":    8 * 1024 * 1024 * 1024,   # 8 GiB
    "gsplat_ckpt":     4 * 1024 * 1024 * 1024,   # 4 GiB
    "gsplat_ply":      4 * 1024 * 1024 * 1024,   # 4 GiB
    "preview_thumb":     5 * 1024 * 1024,        # 5 MiB
    "log":              50 * 1024 * 1024,        # 50 MiB
}

# Allowed lowercase filename extensions per kind. None = any extension.
# Matching is done on the *last* dot-separated segment (case-insensitive).
KIND_ALLOWED_EXT: dict[str, Optional[frozenset[str]]] = {
    "source_image":  frozenset({"jpg", "jpeg", "png", "webp", "tif", "tiff"}),
    "source_video":  frozenset({"mp4", "mov", "avi", "mkv", "webm"}),
    "colmap_sparse": frozenset({"zip", "tar", "tar.gz", "tgz"}),
    "colmap_dense":  frozenset({"zip", "tar", "tar.gz", "tgz", "ply"}),
    "gsplat_ckpt":   frozenset({"ckpt", "pt", "pth", "safetensors"}),
    "gsplat_ply":    frozenset({"ply", "splat"}),
    "preview_thumb": frozenset({"jpg", "jpeg", "png", "webp"}),
    "log":           None,  # allow any log extension
}


def _extract_ext(filename: str) -> str:
    """Extract the lowercase extension including the trailing ``.gz`` for
    tar.gz style compound names. Returns '' if the file has no dot."""
    name = filename.lower().strip()
    # Special-case double extensions.
    for compound in ("tar.gz", "tar.bz2", "tar.xz"):
        if name.endswith("." + compound):
            return compound
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1]


def _validate_kind_policy(kind: str, filename: str, size_bytes: int) -> None:
    """Raise HTTPException if kind/filename/size combo violates policy."""
    if kind not in SCENE_ASSET_KINDS:
        raise HTTPException(400, f"unknown kind {kind!r}")
    max_bytes = KIND_MAX_BYTES.get(kind)
    if max_bytes is not None and size_bytes > max_bytes:
        raise HTTPException(
            413,
            f"{kind} size {size_bytes} exceeds cap {max_bytes} bytes",
        )
    allowed = KIND_ALLOWED_EXT.get(kind)
    if allowed is not None:
        ext = _extract_ext(filename)
        if ext not in allowed:
            raise HTTPException(
                415,
                f"{kind} rejects extension .{ext!r}; "
                f"allowed: {sorted(allowed)}",
            )


# ---------- schemas --------------------------------------------------------


class UploadStart(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(..., description=f"one of {list(SCENE_ASSET_KINDS)}")
    sha256_hex: str = Field(..., min_length=64, max_length=64,
                            pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: int = Field(..., gt=0, le=64 * 1024 * 1024 * 1024)  # 64 GiB hard cap
    total_chunks: int = Field(..., gt=0, le=100_000)


class UploadRef(BaseModel):
    upload_id: str
    filename: str
    kind: str
    sha256_hex: str
    size_bytes: int
    total_chunks: int
    received_chunks: list[int]


class UploadComplete(BaseModel):
    asset_id: UUID
    sha256_hex: str
    size_bytes: int
    filename: str
    dedup: bool  # true if CAS entry already existed


# In-memory upload registry (dev). Prod → move to Redis with TTL.
# Key: (scene_id, upload_id). Value: dict of upload metadata.
_uploads: dict[tuple[UUID, str], dict] = {}


# ---------- helpers --------------------------------------------------------


async def _get_scene(db: AsyncSession, scene_id: UUID, user: User) -> Scene:
    scene = await _load_with_assets(db, scene_id)
    _authz_write(scene, user)
    return scene


def _get_upload(scene_id: UUID, upload_id: str) -> dict:
    rec = _uploads.get((scene_id, upload_id))
    if rec is None:
        raise HTTPException(404, f"upload {upload_id} not found in scene {scene_id}")
    return rec


# ---------- endpoints ------------------------------------------------------


@router.post("", response_model=UploadRef, status_code=201)
async def start_upload(
    scene_id: UUID,
    body: UploadStart,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadRef:
    if body.kind not in SCENE_ASSET_KINDS:
        raise HTTPException(400, f"unknown kind {body.kind!r}")
    # T9.15 · per-kind ingest policy (size cap + filename extension).
    _validate_kind_policy(
        kind=body.kind,
        filename=body.filename,
        size_bytes=body.size_bytes,
    )
    scene = await _get_scene(db, scene_id, user)
    if scene.status not in ("draft", "ingesting"):
        raise HTTPException(
            409, f"scene status {scene.status!r} does not accept uploads"
        )

    # T9.15 · 4DGS scenes must have exactly one source_video. Reject a
    # second attempt so the ingest step has an unambiguous input.
    if body.kind == "source_video":
        scene_kind = getattr(scene, "scene_kind", "3dgs")
        if scene_kind != "4dgs":
            raise HTTPException(
                409,
                f"source_video only accepted for 4dgs scenes "
                f"(this scene kind={scene_kind})",
            )
        already_have_video = any(
            a.kind == "source_video" for a in (scene.assets or [])
        )
        if already_have_video:
            raise HTTPException(
                409,
                "4dgs scene already has a source_video; delete it first",
            )

    upload_id = uuid4().hex
    _uploads[(scene_id, upload_id)] = {
        "upload_id": upload_id,
        "scene_id": scene_id,
        "user_id": user.id,
        "filename": body.filename,
        "kind": body.kind,
        "sha256_hex": body.sha256_hex.lower(),
        "size_bytes": body.size_bytes,
        "total_chunks": body.total_chunks,
    }
    return UploadRef(
        upload_id=upload_id,
        filename=body.filename,
        kind=body.kind,
        sha256_hex=body.sha256_hex.lower(),
        size_bytes=body.size_bytes,
        total_chunks=body.total_chunks,
        received_chunks=[],
    )


@router.put("/{upload_id}/chunks/{chunk_idx}")
async def put_chunk(
    scene_id: UUID,
    upload_id: str,
    chunk_idx: int = Path(..., ge=0, le=100_000),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    rec = _get_upload(scene_id, upload_id)
    if rec["user_id"] != user.id and user.role != "admin":
        raise HTTPException(403, "upload owned by another user")
    if chunk_idx >= rec["total_chunks"]:
        raise HTTPException(400, "chunk_idx exceeds total_chunks")
    body = await request.body()
    if len(body) > MAX_CHUNK_BYTES:
        raise HTTPException(413, f"chunk too large ({len(body)} > {MAX_CHUNK_BYTES})")
    if not body:
        raise HTTPException(400, "empty chunk body")
    try:
        store.get_storage().stage_chunk(upload_id, chunk_idx, body)
    except StorageError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "chunk_idx": chunk_idx, "size": len(body)}


@router.get("/{upload_id}", response_model=UploadRef)
async def get_upload_status(
    scene_id: UUID,
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadRef:
    rec = _get_upload(scene_id, upload_id)
    if rec["user_id"] != user.id and user.role != "admin":
        raise HTTPException(403, "upload owned by another user")
    received = store.get_storage().list_chunks(upload_id)
    return UploadRef(
        upload_id=upload_id,
        filename=rec["filename"],
        kind=rec["kind"],
        sha256_hex=rec["sha256_hex"],
        size_bytes=rec["size_bytes"],
        total_chunks=rec["total_chunks"],
        received_chunks=received,
    )


@router.post("/{upload_id}/complete", response_model=UploadComplete)
async def complete_upload(
    scene_id: UUID,
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadComplete:
    rec = _get_upload(scene_id, upload_id)
    if rec["user_id"] != user.id and user.role != "admin":
        raise HTTPException(403, "upload owned by another user")
    scene = await _get_scene(db, scene_id, user)

    # Check dedup ahead of assembly (cheap path)
    backend = store.get_storage()
    from pathlib import Path

    dedup = False
    if isinstance(backend, store.LocalFSBackend):
        dedup = backend._cas_path(rec["sha256_hex"]).exists()

    try:
        ref = backend.assemble(
            upload_id=upload_id,
            expected_sha256=rec["sha256_hex"],
            total_chunks=rec["total_chunks"],
        )
    except StorageChunkMissing as e:
        raise HTTPException(409, str(e))
    except StorageIntegrityError as e:
        raise HTTPException(422, str(e))
    except StorageError as e:
        raise HTTPException(400, str(e))

    # Persist SceneAsset row
    asset = SceneAsset(
        scene_id=scene.id,
        kind=rec["kind"],
        filename=rec["filename"],
        storage_path=ref.storage_path,
        size_bytes=ref.size_bytes,
        sha256_hex=ref.sha256_hex,
        uploaded_by=user.id,
    )
    db.add(asset)

    # Bump n_source_images when appropriate
    if rec["kind"] == "source_image":
        scene.n_source_images = (scene.n_source_images or 0) + 1

    await db.commit()
    await db.refresh(asset)

    _uploads.pop((scene_id, upload_id), None)

    return UploadComplete(
        asset_id=asset.id,
        sha256_hex=ref.sha256_hex,
        size_bytes=ref.size_bytes,
        filename=asset.filename,
        dedup=dedup,
    )


@router.delete("/{upload_id}", status_code=204)
async def abort_upload(
    scene_id: UUID,
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from fastapi import Response
    rec = _uploads.get((scene_id, upload_id))
    if rec is None:
        return Response(status_code=204)  # idempotent
    if rec["user_id"] != user.id and user.role != "admin":
        raise HTTPException(403, "upload owned by another user")
    store.get_storage().delete_staging(upload_id)
    _uploads.pop((scene_id, upload_id), None)
    return Response(status_code=204)
