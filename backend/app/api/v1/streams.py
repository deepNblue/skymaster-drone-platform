"""Video stream endpoints — MediaMTX (HLS/RTSP) integration."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse

from app.deps import get_current_user
from app.models.user import User
from app.schemas.stream import StreamOut, StreamRegisterRequest
from app.services.stream_manager import (
    StreamManager,
    StreamManagerError,
    get_stream_manager,
)

router = APIRouter(prefix="/streams", tags=["streams"])


def _sm() -> StreamManager:
    """Dependency: return the singleton StreamManager."""
    return get_stream_manager()


@router.post(
    "/{drone_id}/register",
    response_model=StreamOut,
    status_code=status.HTTP_201_CREATED,
)
async def register_stream(
    drone_id: UUID,
    body: StreamRegisterRequest,
    manager: StreamManager = Depends(_sm),
    user: User = Depends(get_current_user),
) -> StreamOut:
    """Register a mediamtx path for a drone video downlink.

    Body: ``{"source_url": "rtsp://..."}``.
    Returns the public HLS + RTSP playback URLs.
    """
    try:
        info = await manager.register_stream(drone_id, body.source_url)
    except StreamManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"mediamtx register failed: {exc}",
        ) from exc
    return StreamOut(**info)


@router.delete(
    "/{drone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def unregister_stream(
    drone_id: UUID,
    manager: StreamManager = Depends(_sm),
    user: User = Depends(get_current_user),
) -> Response:
    """Remove the mediamtx path for a drone."""
    try:
        await manager.unregister_stream(drone_id)
    except StreamManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"mediamtx unregister failed: {exc}",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{drone_id}/hls")
async def get_hls(
    drone_id: UUID,
    manager: StreamManager = Depends(_sm),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the HLS m3u8 playback URL for a drone."""
    return {
        "drone_id": str(drone_id),
        "hls_url": manager.get_hls_url(drone_id),
        "rtsp_url": manager.get_rtsp_url(drone_id),
    }


@router.get("/{drone_id}/snapshot")
async def get_snapshot(
    drone_id: UUID,
    manager: StreamManager = Depends(_sm),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Proxy a JPEG snapshot from mediamtx."""
    try:
        data = await manager.get_snapshot(drone_id)
    except StreamManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"mediamtx snapshot failed: {exc}",
        ) from exc

    async def _iter() -> Any:
        yield data

    return StreamingResponse(_iter(), media_type="image/jpeg")


@router.get("")
async def list_streams(
    manager: StreamManager = Depends(_sm),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List all active mediamtx paths."""
    try:
        items = await manager.list_active_streams()
    except StreamManagerError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"mediamtx list failed: {exc}",
        ) from exc
    return {"items": items, "count": len(items)}
