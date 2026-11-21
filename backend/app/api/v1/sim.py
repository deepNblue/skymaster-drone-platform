"""Dev-only simulation control API.

These endpoints let the frontend command **FakeDrone** processes without going
through the full mission ORM / MAVLink COMMAND_LONG flow. Each FakeDrone
exposes a tiny HTTP server (see ``scripts/fake_drone.py --command-http PORT``);
this router simply proxies mission-editor button clicks to that endpoint.

Enabled only when ``SIM_MODE=true`` env var is set (default: on in dev_stack).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import Role, get_current_user_optional, require_min_role
from app.models.user import User

router = APIRouter(prefix="/sim", tags=["sim"])


# --- registry: sysid → command HTTP port ------------------------------------
def _default_registry() -> dict[int, int]:
    """Parse SIM_DRONES env var, e.g. '1:15001,2:15002' → {1: 15001, 2: 15002}."""
    raw = os.getenv("SIM_DRONES", "1:15001,2:15002")
    out: dict[int, int] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        sid, port = pair.split(":", 1)
        try:
            out[int(sid)] = int(port)
        except ValueError:
            continue
    return out


_REGISTRY: dict[int, int] = _default_registry()


def _drone_port(sysid: int) -> int:
    port = _REGISTRY.get(sysid)
    if not port:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no FakeDrone registered for sysid={sysid} "
                   f"(known: {list(_REGISTRY)})",
        )
    return port


def _post(port: int, body: dict) -> dict:
    """POST to the FakeDrone HTTP command endpoint."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/command",
        data=data, headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"drone rejected: {e.reason}")
    except urllib.error.URLError as e:
        raise HTTPException(
            status_code=503,
            detail=f"cannot reach FakeDrone :{port} — is it running?  ({e.reason})",
        )


# --- schemas ---------------------------------------------------------------
class GotoBody(BaseModel):
    lat: float = Field(..., description="Target latitude")
    lng: float = Field(..., description="Target longitude")
    alt: float = Field(50.0, description="Target altitude (m)")


class Waypoint(BaseModel):
    lat: float
    lng: float
    alt: float = 50.0


class MissionBody(BaseModel):
    waypoints: list[Waypoint] = Field(..., min_length=1, max_length=100)
    skip_compliance: bool = Field(
        default=False,
        description="仿真/调试跳过 UOM+围栏合规检查；生产环境须为 false",
    )


class ModeBody(BaseModel):
    mode: str = Field(..., description="hover | circle | line")


# --- endpoints -------------------------------------------------------------
@router.get("/drones")
def list_sim_drones() -> dict:
    """List all FakeDrones known to this dev stack."""
    return {
        "drones": [
            {"sysid": sid, "command_port": port}
            for sid, port in sorted(_REGISTRY.items())
        ]
    }


@router.get("/drones/{sysid}/state")
def get_state(sysid: int) -> dict:
    """Query the current mode + mission progress of a FakeDrone."""
    port = _drone_port(sysid)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/state", timeout=2) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/drones/{sysid}/goto")
def cmd_goto(sysid: int, body: GotoBody) -> dict:
    """Command drone to fly to (lat, lng, alt)."""
    port = _drone_port(sysid)
    return _post(port, {"type": "goto", **body.model_dump()})


@router.post("/drones/{sysid}/mission")
async def cmd_mission(
    sysid: int,
    body: MissionBody,
    user: User = Depends(require_min_role(Role.OPERATOR)),
) -> dict:
    """Upload a mission (list of waypoints).

    Runs compliance pre-flight checks unless ``skip_compliance=true`` is
    set in the body. Hard-blocks on GeoFence ``no_fly`` violations
    and on missing/expired UOM flight-report coverage.
    """
    waypoints_data = [wp.model_dump() for wp in body.waypoints]

    if not body.skip_compliance:
        # 1. GeoFence check — hard-block no_fly.
        from app.services.geofence import get_geofence
        from app.services.metrics import GEOFENCE_BLOCKS
        gf = get_geofence().check_waypoints(waypoints_data)
        if any(v.kind == "no_fly" for v in gf.violations):
            for v in gf.violations:
                GEOFENCE_BLOCKS.inc(kind=v.kind)
            raise HTTPException(status_code=451, detail={
                "code": "geofence_violation",
                "reason": "任务航点落入禁飞区，无法派发",
                "violations": [v.__dict__ for v in gf.violations],
            })

        # 2. UOM check — require an approved report covering the polygon.
        from app.services.uom_adapter import get_uom
        mission_area = [[wp["lng"], wp["lat"]] for wp in waypoints_data]
        if len(mission_area) >= 3:
            ok, report, reason = await get_uom().check_ready_for_takeoff(mission_area)
            if not ok:
                GEOFENCE_BLOCKS.inc(kind="uom_not_ready")
                raise HTTPException(status_code=451, detail={
                    "code": "uom_not_ready",
                    "reason": reason,
                    "hint": "先在「🛡 飞行报备」提交并等待批准",
                })

    port = _drone_port(sysid)
    result = _post(port, {"type": "mission", "waypoints": waypoints_data})
    from app.services.metrics import MISSIONS_DISPATCHED
    MISSIONS_DISPATCHED.inc()
    if not body.skip_compliance:
        from app.services.geofence import get_geofence
        gf = get_geofence().check_waypoints(waypoints_data)
        result["compliance"] = {
            "geofence": {"ok": gf.ok, "warnings": [v.__dict__ for v in gf.violations]},
            "uom": {"ok": True, "checked": len(waypoints_data) >= 3},
        }
    return result


@router.post("/drones/{sysid}/rtl")
def cmd_rtl(sysid: int) -> dict:
    """Return to launch (home position)."""
    port = _drone_port(sysid)
    return _post(port, {"type": "rtl"})


@router.post("/drones/{sysid}/mode")
def cmd_mode(sysid: int, body: ModeBody) -> dict:
    """Switch to a canned pattern (hover / circle / line)."""
    port = _drone_port(sysid)
    if body.mode not in ("hover", "circle", "line"):
        raise HTTPException(status_code=400, detail=f"invalid mode: {body.mode}")
    return _post(port, {"type": body.mode})


@router.post("/drones/{sysid}/arm")
def cmd_arm(sysid: int) -> dict:
    port = _drone_port(sysid)
    return _post(port, {"type": "arm"})


@router.post("/drones/{sysid}/disarm")
def cmd_disarm(sysid: int) -> dict:
    port = _drone_port(sysid)
    return _post(port, {"type": "disarm"})
