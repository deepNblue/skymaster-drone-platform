"""Mission → 3DGS Scene import endpoint — v2.1 E3.4.

Import all media assets from a completed drone mission into a new 3DGS scene.
Skip the manual upload step for users who already captured imagery during mission.

Workflow:
1. User selects an existing mission (must have status=completed)
2. Backend copies all image/video assets from mission to the new scene
3. Transition the new scene directly to `ingested` state — ready for COLMAP
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.mission import Mission
from app.models.media_asset import MediaAsset
from app.models.scene import Scene, SceneAsset
from app.models.user import User
from app.services import scene_pipeline as sp
from app.services import object_storage as store


router = APIRouter(prefix="/scenes-import", tags=["scenes-import"])


# ---------- Schemas --------------------------------------------------------

class ImportMissionRequest(BaseModel):
    mission_id: UUID
    name: Optional[str] = None
    description: Optional[str] = None
    scene_kind: str = "3dgs"  # 3dgs | 4dgs


class ImportMissionResponse(BaseModel):
    scene_id: UUID
    n_imported: int
    status: str


# ---------- Endpoints -------------------------------------------------------


@router.post("/from-mission", response_model=ImportMissionResponse)
async def import_mission_to_scene(
    req: ImportMissionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportMissionResponse:
    """Import all media assets from a completed mission into a new 3DGS scene.

    Requirements:
     - Mission must belong to the same org as the importing user
     - Mission must be marked as 'completed'
     - Only assets of type 'image' or 'video' are imported (skip telemetry/thumbnails)
    """
    # 1. Load and validate mission
    mission = (
        await db.execute(select(Mission).where(Mission.id == req.mission_id))
    ).scalar_one_or_none()
    if mission is None:
        raise HTTPException(404, f"mission {req.mission_id} not found")

    # Permission check: user can see mission
    if user.role != "admin":
        if mission.org_id != user.org_id:
            raise HTTPException(403, "mission not accessible")
        if mission.created_by != user.id and user.role not in ("system_officer",):
            raise HTTPException(403, "you do not have permission to import this mission")

    if mission.status != "completed":
        raise HTTPException(409, "only completed missions can be imported to 3DGS")

    org_id = mission.org_id or user.org_id
    if org_id is None:
        org_id = user.id  # fallback

    # 2. Create new scene
    scene_name = req.name or f"Imported from {mission.name}"
    scene = Scene(
        org_id=org_id,
        name=scene_name,
        description=req.description or f"Automatically imported from mission {mission.name}",
        status="draft",
        scene_kind=req.scene_kind,
        owner_user_id=user.id,
    )
    db.add(scene)
    await db.flush()

    # 3. Query all importable assets from mission
    assets_query = select(MediaAsset).where(
        MediaAsset.mission_id == mission.id,
        MediaAsset.type.in_(["image", "video"]),
    )
    result = await db.execute(assets_query)
    media_assets = result.scalars().all()

    if len(media_assets) == 0:
        raise HTTPException(400, "mission has no importable image/video assets")

    # 4. Copy references to SceneAsset (we don't copy actual bytes — both use object storage)
    # The media assets are already stored in object storage by the mission, reuse their existing keys.
    n_imported = 0
    for ma in media_assets:
        # Guess asset kind from type
        kind = "source_image" if ma.type == "image" else "source_video"

        sa = SceneAsset(
            scene_id=scene.id,
            kind=kind,
            filename=ma.minio_key.split("/")[-1],
            storage_path=f"scenes/{scene.id}/{ma.minio_key}",
            size_bytes=ma.size_bytes,
            sha256_hex=None,  # We already trust the mission asset hash
            uploaded_by=user.id,
        )
        db.add(sa)
        n_imported += 1

    # 5. Transition directly to ingested — all assets are already uploaded
    await sp.transition(db, scene, "ingested")
    if req.scene_kind == "4dgs":
        # For 4DGS from mission video, n_frames will be set after ingestion by executor
        pass

    # 6. Commit and return
    await db.commit()
    await db.refresh(scene)

    return ImportMissionResponse(
        scene_id=scene.id,
        n_imported=n_imported,
        status=scene.status,
    )
