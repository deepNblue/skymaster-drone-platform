"""Remote ID broadcast API — v2.0 civil aviation compliance.

Public read endpoints intended for regulators / third-party ATM systems.
Internal ingest endpoint is fed by the mission-watcher when telemetry arrives.

Endpoints:
    GET  /api/v1/remoteid/messages         → all in-flight aircraft
    GET  /api/v1/remoteid/messages/{uas}   → single aircraft snapshot
    POST /api/v1/remoteid/broadcast        → operator publishes (op-role)
    DELETE /api/v1/remoteid/messages/{uas} → admin clears (test only)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import Role, get_current_user_optional, require_min_role
from app.services.remoteid import RemoteIDMessage, publish, get_all, get_one
from app.services.remoteid import clear as _clear

router = APIRouter(prefix="/remoteid", tags=["remoteid"])


class BroadcastBody(BaseModel):
    uas_id: str = Field(..., description="Aircraft registration / session token")
    uas_id_type: int = 1
    lat: float
    lng: float
    alt_m: float = 0
    track_deg: float = 0
    speed_ms: float = 0
    vertical_rate_ms: float = 0
    height_agl_m: float = 0
    operator_id: str = ""
    status: str = "airborne"
    home_lat: float | None = None
    home_lng: float | None = None


@router.get("/messages")
async def list_messages(user=Depends(get_current_user_optional)) -> dict:
    return {"messages": get_all()}


@router.get("/messages/{uas_id}")
async def one_message(
    uas_id: str, user=Depends(get_current_user_optional),
) -> dict:
    msg = get_one(uas_id)
    if not msg:
        raise HTTPException(404, f"No Remote ID broadcast for uas_id={uas_id}")
    return msg


@router.post("/broadcast", status_code=201)
async def broadcast(
    body: BroadcastBody,
    user=Depends(require_min_role(Role.OPERATOR)),
) -> dict:
    """Publish a Remote ID position update.

    Operator role required. In prod this would come from onboard telemetry.
    """
    msg = RemoteIDMessage(**body.model_dump())
    publish(msg)
    try:
        from app.services.metrics import HTTP_REQ_TOTAL  # noqa: F401
        # (Metrics middleware already counts HTTP; nothing custom needed.)
    except ImportError:
        pass
    return {"ok": True, "uas_id": body.uas_id, "ts": msg.timestamp}


@router.delete("/messages/{uas_id}")
async def clear_one(
    uas_id: str, user=Depends(require_min_role(Role.ADMIN)),
) -> dict:
    from app.services.remoteid import _STATE
    if uas_id in _STATE:
        _STATE.pop(uas_id)
    return {"ok": True}


@router.post("/_test/clear")
async def test_clear(user=Depends(require_min_role(Role.ADMIN))) -> dict:
    """Clear all Remote ID broadcasts (test/dev hook)."""
    _clear()
    return {"ok": True, "cleared": True}
