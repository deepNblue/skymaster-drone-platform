"""DJI Cloud API control endpoints.

Thin HTTP façade over the ``DJICloudConnector`` instance that lives in
``app.state.dji_connector`` (wired by the telemetry stack in main.py). Lets
the frontend joystick panel issue DRC stick commands and fleet actions without
touching the connector object directly.

When no connector is mounted (telemetry stack disabled or no DJI drones), the
endpoints return 503 with an actionable message instead of crashing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.deps import get_current_user_optional
from app.models.user import User

router = APIRouter(prefix="/dji", tags=["dji"])


def _connector(request: Request) -> Any:
    conn = getattr(request.app.state, "dji_connector", None)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "DJI connector not mounted. Start with START_TELEMETRY_STACK=true "
                "and add a Drone with protocol='dji' + metadata.dji_device_sn."
            ),
        )
    return conn


class DRCBody(BaseModel):
    drone_sn: str = Field(..., description="DJI device SN (metadata.dji_device_sn)")
    throttle: float = Field(0.0, ge=-1.0, le=1.0)
    yaw: float = Field(0.0, ge=-1.0, le=1.0)
    pitch: float = Field(0.0, ge=-1.0, le=1.0)
    roll: float = Field(0.0, ge=-1.0, le=1.0)


class ActionBody(BaseModel):
    action: str = Field(..., description="return_home | live_start | hover")
    drone_sn: str
    rtmp_url: Optional[str] = None
    waypoints: Optional[List[Dict[str, float]]] = None


class RCAxisBody(BaseModel):
    min: float = Field(..., ge=-1.0, le=1.0)
    center: float = Field(..., ge=-1.0, le=1.0)
    max: float = Field(..., ge=-1.0, le=1.0)


class RCCalibrationBody(BaseModel):
    drone_sn: str
    axes: Dict[str, RCAxisBody]
    deadzone: Optional[float] = Field(None, ge=0.0, le=0.5)


class CalibrationBody(BaseModel):
    drone_sn: str
    item: str = Field(..., description="compass | imu | gimbal | vision | rc")


@router.get("/status")
async def dji_status(
    request: Request,
    user: User = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """Connector status, known aircraft and last DRC axes per aircraft."""
    conn = _connector(request)
    known = list(getattr(conn, "drone_id_map", {}).keys()) or [
        d["sn"] for d in getattr(conn, "topology", {}).get("sub_devices", [])
    ]
    return {
        "available": True,
        "mode": getattr(conn, "mode", "?"),
        "gateway_sn": getattr(conn, "gateway_sn", "?"),
        "connected": getattr(conn, "_connected", False),
        "aircraft": known,
        "last_drc": getattr(conn, "last_drc", {}),
        "drc_link": (conn.drc_link_status()
                     if hasattr(conn, "drc_link_status") else {}),
        "states": getattr(conn, "_mock_state", {}),
        "reconnect_attempt": getattr(conn, "_reconnect_attempt", 0),
    }


@router.post("/drc")
async def send_drc(
    body: DRCBody,
    request: Request,
    user: User = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """Send a real-time stick command (4 axes in [-1, 1])."""
    conn = _connector(request)
    ok = conn.send_drc(
        body.drone_sn,
        throttle=body.throttle, yaw=body.yaw,
        pitch=body.pitch, roll=body.roll,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MQTT not connected — DRC command not sent",
        )
    return {
        "ok": True,
        "drone_sn": body.drone_sn,
        "axes": {
            "throttle": body.throttle, "yaw": body.yaw,
            "pitch": body.pitch, "roll": body.roll,
        },
    }


@router.post("/action")
async def send_action(
    body: ActionBody,
    request: Request,
    user: User = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """Fleet actions: return_home / live_start / hover."""
    conn = _connector(request)
    action = body.action.lower()
    if action == "return_home":
        ok = conn.return_home(body.drone_sn)
    elif action == "live_start":
        if not body.rtmp_url:
            raise HTTPException(status_code=422, detail="rtmp_url required for live_start")
        ok = conn.start_live(body.drone_sn, body.rtmp_url)
    elif action == "hover":
        ok = conn.send_drc(body.drone_sn)  # neutral sticks => hover
    elif action == "mission":
        if not body.waypoints:
            raise HTTPException(status_code=422, detail="waypoints required for mission")
        ok = conn.flighttask_prepare(body.drone_sn, body.waypoints)
        if ok:
            conn.flighttask_execute("api-task", "api-flight")
    else:
        raise HTTPException(status_code=422, detail=f"unknown action: {action}")
    if not ok:
        raise HTTPException(status_code=503, detail="MQTT not connected — action not sent")
    return {"ok": True, "action": action, "drone_sn": body.drone_sn}


@router.get("/calibration/status")
async def calibration_status(
    request: Request,
    drone_sn: Optional[str] = None,
    user: User = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """Calibration items, per-aircraft state machine and saved RC endpoints."""
    conn = _connector(request)
    return conn.calibration_status(drone_sn)


@router.post("/calibration/start")
async def calibration_start(
    body: CalibrationBody,
    request: Request,
    user: User = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    conn = _connector(request)
    valid = {i["key"] for i in conn.calibration_items()}
    if body.item not in valid:
        raise HTTPException(status_code=422, detail=f"unknown calibration item: {body.item}")
    ok = conn.start_calibration(body.drone_sn, body.item)
    if not ok:
        raise HTTPException(status_code=503, detail="calibration command not sent")
    return {"ok": True, "drone_sn": body.drone_sn, "item": body.item}


@router.post("/calibration/cancel")
async def calibration_cancel(
    body: CalibrationBody,
    request: Request,
    user: User = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    conn = _connector(request)
    ok = conn.cancel_calibration(body.drone_sn, body.item)
    if not ok:
        raise HTTPException(status_code=404, detail="no active calibration to cancel")
    return {"ok": True, "drone_sn": body.drone_sn, "item": body.item}


@router.post("/calibration/rc")
async def calibration_rc(
    body: RCCalibrationBody,
    request: Request,
    user: User = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """Save RC endpoints captured by the calibration wizard."""
    conn = _connector(request)
    from app.services.dji_cloud_connector import RC_AXES

    axes: Dict[str, Dict[str, float]] = {}
    for axis in RC_AXES:
        entry = body.axes.get(axis)
        if entry is None:
            raise HTTPException(status_code=422, detail=f"missing axis: {axis}")
        if not (entry.min < entry.center < entry.max):
            raise HTTPException(
                status_code=422,
                detail=f"{axis}: require min < center < max",
            )
        axes[axis] = {"min": entry.min, "center": entry.center, "max": entry.max}
    ok = conn.set_rc_calibration(body.drone_sn, axes, body.deadzone)
    if not ok:
        raise HTTPException(status_code=422, detail="invalid RC calibration payload")
    return {
        "ok": True,
        "drone_sn": body.drone_sn,
        "deadzone": conn._rc_calibration[body.drone_sn]["deadzone"],
        "axes": axes,
    }
