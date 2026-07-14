"""UOM 集成 API — v2.0 Track A A3.

Wraps the ``UomClient`` facade in a FastAPI router so the platform's own
flight-approval workflow (§3.14 / R21 approvals) can call UOM checks,
and so admins can pre-register pilots + aircraft.

Endpoints (``/api/v1/uom``):
* ``POST /pilots``              register pilot (real-name)
* ``POST /aircrafts``           register aircraft
* ``POST /airspace/check``      pre-flight airspace verdict
* ``POST /flight-plans``        submit a flight plan
* ``GET  /flight-plans/{ref}``  retrieve a submitted plan by UOM ref
* ``GET  /status``              mode + auth status
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.models.user import User
from app.services.uom_client import (
    AircraftInfo, AirspaceQuery, AirspaceVerdict, FlightPlan, PilotInfo,
    UomClient, get_mode, hash_id_card,
)

router = APIRouter(prefix="/uom", tags=["uom"])


def _client() -> UomClient:
    return UomClient()


def _require_writer(user: User) -> None:
    if getattr(user, "role", None) not in {"admin", "operator"}:
        raise HTTPException(403, "admin or operator only")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PilotIn(BaseModel):
    pilot_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    id_card: str = Field(min_length=15, max_length=18)
    license_no: Optional[str] = Field(None, max_length=64)
    license_class: Optional[str] = Field(None, max_length=32)


class AircraftIn(BaseModel):
    reg_no: str = Field(min_length=1, max_length=32)
    manufacturer: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=64)
    serial: str = Field(min_length=1, max_length=64)
    mtow_kg: float = Field(gt=0, le=150.0)
    category: str = Field(pattern="^(微|轻|小|中|大)$")


class AirspaceIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    altitude_m: float = Field(ge=0, le=6000)
    radius_m: float = Field(default=500, ge=1, le=100_000)
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None


class AirspaceOut(BaseModel):
    allowed: bool
    zone_type: str
    ceiling_m: Optional[float]
    reason: str
    references: list[str]


class FlightPlanIn(BaseModel):
    plan_id: str = Field(min_length=1, max_length=64)
    pilot_id: str
    aircraft_reg: str
    lat: float
    lng: float
    altitude_m: float
    start_ts: str
    end_ts: str
    purpose: str
    contact_phone: str
    attachments: list[str] = []


class UomAckOut(BaseModel):
    plan_id: str
    uom_ref_no: str
    status: str
    reviewer: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def uom_status(user: User = Depends(get_current_user)) -> dict:
    return {
        "mode": get_mode(),
        "authorized": False if get_mode() == "mock" else True,
        "note": (
            "UOM live 授权申请周期 6-12 周；当前 mock 模式下的空域数据"
            "为演示用途，不能替代真实合规判断。"
        ),
    }


@router.post("/pilots")
async def register_pilot(body: PilotIn, user: User = Depends(get_current_user)) -> dict:
    _require_writer(user)
    pilot = PilotInfo(
        pilot_id=body.pilot_id,
        name=body.name,
        id_card_hash=hash_id_card(body.id_card),
        license_no=body.license_no,
        license_class=body.license_class,
    )
    return _client().register_pilot(pilot)


@router.post("/aircrafts")
async def register_aircraft(body: AircraftIn, user: User = Depends(get_current_user)) -> dict:
    _require_writer(user)
    ac = AircraftInfo(
        reg_no=body.reg_no, manufacturer=body.manufacturer,
        model=body.model, serial=body.serial,
        mtow_kg=body.mtow_kg, category=body.category,
    )
    return _client().register_aircraft(ac)


@router.post("/airspace/check", response_model=AirspaceOut)
async def check_airspace(body: AirspaceIn, user: User = Depends(get_current_user)) -> AirspaceOut:
    v = _client().check_airspace(AirspaceQuery(
        lat=body.lat, lng=body.lng, altitude_m=body.altitude_m,
        radius_m=body.radius_m,
        start_ts=body.start_ts, end_ts=body.end_ts,
    ))
    return AirspaceOut(
        allowed=v.allowed, zone_type=v.zone_type,
        ceiling_m=v.ceiling_m, reason=v.reason, references=v.references,
    )


@router.post("/flight-plans", response_model=UomAckOut)
async def submit_flight_plan(
    body: FlightPlanIn, user: User = Depends(get_current_user),
) -> UomAckOut:
    _require_writer(user)
    plan = FlightPlan(
        plan_id=body.plan_id, pilot_id=body.pilot_id,
        aircraft_reg=body.aircraft_reg,
        lat=body.lat, lng=body.lng, altitude_m=body.altitude_m,
        start_ts=body.start_ts, end_ts=body.end_ts,
        purpose=body.purpose, contact_phone=body.contact_phone,
        attachments=body.attachments,
    )
    ack = _client().submit_plan(plan)
    return UomAckOut(
        plan_id=ack.plan_id, uom_ref_no=ack.uom_ref_no,
        status=ack.status, reviewer=ack.reviewer,
        valid_from=ack.valid_from, valid_to=ack.valid_to,
        reason=ack.reason,
    )


@router.get("/flight-plans/{ref}")
async def get_flight_plan(ref: str, user: User = Depends(get_current_user)) -> dict:
    plan = _client().get_plan(ref)
    if plan is None:
        raise HTTPException(404, "UOM plan not found")
    return plan


# ---------------------------------------------------------------------------
# Reports (in-process adapter, back-compat wrapper for /reports endpoints
# used by tests test_uom.py, test_uom_multitenant.py, test_audit_middleware.py
# and test_compliance_integration.py)
# ---------------------------------------------------------------------------


class ReportCreate(BaseModel):
    operator_id: str = Field(min_length=1, max_length=64)
    pilot_name: str = Field(min_length=1, max_length=64)
    aircraft_reg: str = Field(min_length=1, max_length=64)
    purpose: str = Field(min_length=1, max_length=128)
    area_polygon: list[list[float]] = Field(min_length=3)
    max_alt_m: float = Field(gt=0, le=500)
    start_ts: float
    end_ts: float


class ReportApprove(BaseModel):
    reviewer: str = Field(default="auto-uom", max_length=64)


class ReportReject(BaseModel):
    reviewer: str = Field(default="auto-uom", max_length=64)
    reason: str = Field(min_length=1, max_length=200)


def _adapter():
    """Return the module-level UOMAdapter singleton."""
    from app.services.uom_adapter import get_uom
    return get_uom()


def _report_to_dict(r) -> dict:
    return {
        "id": r.id,
        "operator_id": r.operator_id,
        "pilot_name": r.pilot_name,
        "aircraft_reg": r.aircraft_reg,
        "purpose": r.purpose,
        "area_polygon": r.area_polygon,
        "max_alt_m": r.max_alt_m,
        "start_ts": r.start_ts,
        "end_ts": r.end_ts,
        "status": r.status.value if hasattr(r.status, "value") else r.status,
        "submitted_at": r.submitted_at,
        "reviewed_at": r.reviewed_at,
        "reviewer": r.reviewer,
        "reject_reason": r.reject_reason,
        "approval_code": r.approval_code,
    }


@router.post("/reports", status_code=201)
async def create_report(body: ReportCreate) -> dict:
    try:
        report = await _adapter().submit(
            operator_id=body.operator_id,
            pilot_name=body.pilot_name,
            aircraft_reg=body.aircraft_reg,
            purpose=body.purpose,
            area_polygon=body.area_polygon,
            max_alt_m=body.max_alt_m,
            start_ts=body.start_ts,
            end_ts=body.end_ts,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _report_to_dict(report)


@router.get("/reports")
async def list_reports(
    status: Optional[str] = None,
    operator_id: Optional[str] = None,
) -> dict:
    """Return {reports, count, scoped_by}. Operator scope for multi-tenant.
    """
    from app.services.uom_adapter import ReportStatus
    status_enum = None
    if status:
        try:
            status_enum = ReportStatus(status)
        except ValueError:
            raise HTTPException(400, f"invalid status={status!r}")
    reports = await _adapter().list_all(status=status_enum, operator_id=operator_id)
    return {
        "reports": [_report_to_dict(r) for r in reports],
        "count": len(reports),
        "scoped_by": operator_id,
    }


@router.get("/reports/{rid}")
async def get_report(rid: str) -> dict:
    r = await _adapter().get(rid)
    if not r:
        raise HTTPException(404, "report not found")
    return _report_to_dict(r)


@router.post("/reports/{rid}/approve")
async def approve_report(rid: str, body: ReportApprove) -> dict:
    try:
        r = await _adapter().approve(rid, reviewer=body.reviewer)
    except KeyError:
        raise HTTPException(404, "report not found")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _report_to_dict(r)


@router.post("/reports/{rid}/reject")
async def reject_report(rid: str, body: ReportReject) -> dict:
    try:
        r = await _adapter().reject(rid, reason=body.reason, reviewer=body.reviewer)
    except KeyError:
        raise HTTPException(404, "report not found")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _report_to_dict(r)


@router.post("/reports/{rid}/cancel")
async def cancel_report(rid: str) -> dict:
    try:
        r = await _adapter().cancel(rid)
    except KeyError:
        raise HTTPException(404, "report not found")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _report_to_dict(r)


# ---------------------------------------------------------------------------
# Airspace pre-check via adapter (test_uom.py::test_uom_full_flow_via_api)
# ---------------------------------------------------------------------------


class UomCheckIn(BaseModel):
    mission_area: list[list[float]] = Field(min_length=3)
    at_ts: float


@router.post("/check")
async def uom_check(body: UomCheckIn) -> dict:
    ok, report, reason = await _adapter().check_ready_for_takeoff(
        body.mission_area, now_ts=body.at_ts,
    )
    return {
        "ok": ok,
        "reason": reason,
        "report_id": report.id if report else None,
        "approval_code": report.approval_code if report else None,
    }
