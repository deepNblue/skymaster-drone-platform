"""Tool registry for Copilot v0.1 (SDD v2.0-C §7).

Registers the 6 read-only tools listed as v0.1 targets. Sensitive
mutation tools (create_mission / dispatch_mission / abort_mission /
submit_approval) are scoped out of v0.1 and will land alongside the
Approval Gate execution path.

Each tool is an ``async`` callable with a pydantic ``args_schema``.
``get_specs()`` returns Anthropic-style ``tools`` metadata suitable for
Function Calling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drone import Drone
from app.models.mission import Mission
from app.models.vision_copilot import VisionDetection


# ---------------------------------------------------------------------------
# Tool context — passed to every tool at call time
# ---------------------------------------------------------------------------
@dataclass
class ToolContext:
    """Runtime context for a tool call — auth + DB session."""

    db: AsyncSession | None = None
    org_id: UUID | None = None
    user_id: UUID | None = None


# ---------------------------------------------------------------------------
# Pydantic arg schemas
# ---------------------------------------------------------------------------
class ListDronesArgs(BaseModel):
    """No arguments — lists drones visible to the current org."""


class GetDroneStatusArgs(BaseModel):
    drone_id: str = Field(..., description="UUID of the target drone")


class CheckAirspaceArgs(BaseModel):
    geo: list[list[float]] = Field(
        ...,
        description=(
            "Polygon or path as a list of [lng, lat] pairs to check against "
            "no-fly zones"
        ),
    )


class QueryWeatherArgs(BaseModel):
    lat: float
    lng: float


class ListMissionsArgs(BaseModel):
    """No arguments — lists recent missions for the current org."""


class GetMissionDetailArgs(BaseModel):
    mission_id: str = Field(..., description="UUID of the target mission")


# --- Sensitive (mutation) tools — require approval before execution ------

class CreateMissionArgs(BaseModel):
    name: str = Field(..., description="Human-readable mission name")
    drone_id: str = Field(..., description="UUID of the drone to assign")
    waypoints: list[list[float]] = Field(
        ..., description="Ordered list of [lng, lat, alt_m] waypoints"
    )
    template: str | None = Field(
        None, description="Optional template hint (e.g. 'patrol', 'inspect')"
    )


class DispatchMissionArgs(BaseModel):
    mission_id: str = Field(..., description="UUID of the mission to dispatch")


class AbortMissionArgs(BaseModel):
    mission_id: str = Field(..., description="UUID of the mission to abort")
    reason: str | None = Field(None, description="Optional reason for the abort")


# --- Vision AI query tools (T5.0) ------------------------------------------
# All readonly. Let Copilot v2 answer questions like
# "最近有没有识别到人?" / "D1 过去 10 分钟看到了什么?"

class ListDetectionsArgs(BaseModel):
    drone_id: str | None = Field(
        None, description="Optional UUID filter — restrict to a single drone"
    )
    mission_id: str | None = Field(
        None, description="Optional UUID filter — restrict to a single mission"
    )
    label: str | None = Field(
        None, description="Optional class label filter (e.g. 'person', 'vehicle')"
    )
    min_confidence: float | None = Field(
        None, ge=0.0, le=1.0,
        description="Minimum confidence in [0,1]; None means no lower bound",
    )
    since_minutes: int | None = Field(
        None, ge=1, le=1440,
        description="Only include detections created in the last N minutes",
    )
    limit: int = Field(20, ge=1, le=200, description="Max rows to return")


class DetectionStatsArgs(BaseModel):
    drone_id: str | None = Field(
        None, description="Optional UUID filter — restrict to a single drone"
    )
    since_minutes: int = Field(
        60, ge=1, le=1440,
        description="Aggregate over the trailing N minutes (default 60)",
    )



# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
async def list_drones(ctx: ToolContext, args: ListDronesArgs) -> dict[str, Any]:
    if ctx.db is None:
        return {"drones": []}
    stmt = select(Drone)
    if ctx.org_id is not None:
        stmt = stmt.where(Drone.org_id == ctx.org_id)
    stmt = stmt.limit(50)
    rows = (await ctx.db.execute(stmt)).scalars().all()
    return {
        "drones": [
            {
                "id": str(d.id),
                "sn": d.sn,
                "model": d.model,
                "status": d.status,
            }
            for d in rows
        ]
    }


async def get_drone_status(
    ctx: ToolContext, args: GetDroneStatusArgs
) -> dict[str, Any]:
    if ctx.db is None:
        return {"found": False, "reason": "no db session"}
    try:
        drone_uuid = UUID(args.drone_id)
    except ValueError:
        return {"found": False, "reason": "invalid drone_id"}
    stmt = select(Drone).where(Drone.id == drone_uuid)
    drone = (await ctx.db.execute(stmt)).scalar_one_or_none()
    if drone is None:
        return {"found": False}
    return {
        "found": True,
        "id": str(drone.id),
        "sn": drone.sn,
        "status": drone.status,
        "model": drone.model,
    }


# Hardcoded no-fly zone blocklist for the placeholder implementation.
# In v2.0 this will consult the UOM airspace API.
_NOFLY_KEYWORDS = ("long'an street", "长安街")


async def check_airspace(
    ctx: ToolContext, args: CheckAirspaceArgs
) -> dict[str, Any]:
    """Placeholder airspace check. Real implementation lives in Track A."""
    # v0.1: cheap heuristic — we don't have GIS integration yet, so
    # unless the caller pushed geo text into a special sentinel value
    # we always return {ok: true}. Explicit blocklist tests can pass
    # a single sentinel point at lat=long lng=an to trigger deny.
    if args.geo and len(args.geo[0]) >= 3:
        # allow caller to pass a name string as third element
        label = str(args.geo[0][2]).lower() if len(args.geo[0]) > 2 else ""
        if any(k in label for k in _NOFLY_KEYWORDS):
            return {
                "ok": False,
                "reason": "intersects known no-fly zone (placeholder)",
                "zone": label,
            }
    return {"ok": True, "checked_points": len(args.geo)}


async def query_weather(
    ctx: ToolContext, args: QueryWeatherArgs
) -> dict[str, Any]:
    """Mock weather. Real implementation would call a weather provider."""
    return {"temp": 20, "wind": "5m/s", "condition": "clear"}


async def list_missions(
    ctx: ToolContext, args: ListMissionsArgs
) -> dict[str, Any]:
    if ctx.db is None:
        return {"missions": []}
    stmt = select(Mission)
    if ctx.org_id is not None:
        stmt = stmt.where(Mission.org_id == ctx.org_id)
    stmt = stmt.order_by(Mission.created_at.desc()).limit(50)
    rows = (await ctx.db.execute(stmt)).scalars().all()
    return {
        "missions": [
            {
                "id": str(m.id),
                "name": m.name,
                "status": m.status,
                "template": m.template,
            }
            for m in rows
        ]
    }


async def get_mission_detail(
    ctx: ToolContext, args: GetMissionDetailArgs
) -> dict[str, Any]:
    if ctx.db is None:
        return {"found": False, "reason": "no db session"}
    try:
        mid = UUID(args.mission_id)
    except ValueError:
        return {"found": False, "reason": "invalid mission_id"}
    stmt = select(Mission).where(Mission.id == mid)
    mission = (await ctx.db.execute(stmt)).scalar_one_or_none()
    if mission is None:
        return {"found": False}
    return {
        "found": True,
        "id": str(mission.id),
        "name": mission.name,
        "status": mission.status,
        "template": mission.template,
        "waypoints": mission.waypoints,
    }


# --- Sensitive mutation tools --------------------------------------------
#
# These are the tools that touch fleet state. The agent loop routes them
# through the CopilotApproval gate — the ``func`` here IS the executor
# that runs AFTER an approver clicks "approve". Never invoke these
# directly from the agent loop; call ``CopilotAgentV2._enqueue_approval``
# instead.

async def create_mission(
    ctx: ToolContext, args: CreateMissionArgs,
) -> dict[str, Any]:
    if ctx.db is None:
        return {"ok": False, "reason": "no db session"}
    try:
        drone_uuid = UUID(args.drone_id)
    except ValueError:
        return {"ok": False, "reason": "invalid drone_id"}
    mission = Mission(
        id=uuid4(),
        org_id=ctx.org_id,
        drone_id=drone_uuid,
        name=args.name,
        template=args.template,
        status="planned",
        waypoints=args.waypoints,
    )
    ctx.db.add(mission)
    await ctx.db.flush()
    return {
        "ok": True, "mission_id": str(mission.id),
        "status": mission.status, "name": mission.name,
    }


async def dispatch_mission(
    ctx: ToolContext, args: DispatchMissionArgs,
) -> dict[str, Any]:
    if ctx.db is None:
        return {"ok": False, "reason": "no db session"}
    try:
        mid = UUID(args.mission_id)
    except ValueError:
        return {"ok": False, "reason": "invalid mission_id"}
    mission = (
        await ctx.db.execute(select(Mission).where(Mission.id == mid))
    ).scalar_one_or_none()
    if mission is None:
        return {"ok": False, "reason": "mission not found"}
    if mission.status not in ("planned", "queued"):
        return {"ok": False, "reason": f"mission is in status {mission.status!r}, cannot dispatch"}
    mission.status = "dispatched"
    await ctx.db.flush()
    return {"ok": True, "mission_id": str(mission.id), "status": mission.status}


async def abort_mission(
    ctx: ToolContext, args: AbortMissionArgs,
) -> dict[str, Any]:
    if ctx.db is None:
        return {"ok": False, "reason": "no db session"}
    try:
        mid = UUID(args.mission_id)
    except ValueError:
        return {"ok": False, "reason": "invalid mission_id"}
    mission = (
        await ctx.db.execute(select(Mission).where(Mission.id == mid))
    ).scalar_one_or_none()
    if mission is None:
        return {"ok": False, "reason": "mission not found"}
    if mission.status in ("completed", "aborted", "canceled"):
        return {"ok": False, "reason": f"mission already terminal ({mission.status})"}
    mission.status = "aborted"
    await ctx.db.flush()
    return {"ok": True, "mission_id": str(mission.id), "status": mission.status, "reason": args.reason}


# ---------------------------------------------------------------------------
# Vision AI tools (T5.0)
# ---------------------------------------------------------------------------
async def list_detections(
    ctx: ToolContext, args: ListDetectionsArgs,
) -> dict[str, Any]:
    """Return recent vision detections filtered by drone / mission / label."""
    if ctx.db is None:
        return {"detections": [], "reason": "no db session"}
    from datetime import datetime, timedelta, timezone

    stmt = select(VisionDetection)
    if ctx.org_id is not None:
        stmt = stmt.where(VisionDetection.tenant_id == ctx.org_id)
    if args.drone_id:
        try:
            stmt = stmt.where(VisionDetection.drone_id == UUID(args.drone_id))
        except ValueError:
            return {"detections": [], "reason": "invalid drone_id"}
    if args.mission_id:
        try:
            stmt = stmt.where(VisionDetection.mission_id == UUID(args.mission_id))
        except ValueError:
            return {"detections": [], "reason": "invalid mission_id"}
    if args.label:
        stmt = stmt.where(VisionDetection.label == args.label)
    if args.min_confidence is not None:
        stmt = stmt.where(VisionDetection.confidence >= args.min_confidence)
    if args.since_minutes is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=args.since_minutes)
        stmt = stmt.where(VisionDetection.created_at >= cutoff)
    stmt = stmt.order_by(VisionDetection.created_at.desc()).limit(args.limit)
    rows = (await ctx.db.execute(stmt)).scalars().all()
    return {
        "count": len(rows),
        "detections": [
            {
                "id": str(d.id),
                "drone_id": str(d.drone_id) if d.drone_id else None,
                "mission_id": str(d.mission_id) if d.mission_id else None,
                "label": d.label,
                "confidence": d.confidence,
                "bbox": d.bbox,
                "stream_key": d.stream_key,
                "model_tag": d.model_tag,
                "runtime": d.runtime,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in rows
        ],
    }


async def detection_stats(
    ctx: ToolContext, args: DetectionStatsArgs,
) -> dict[str, Any]:
    """Aggregate detection counts by label over the trailing N minutes."""
    if ctx.db is None:
        return {"by_label": {}, "reason": "no db session"}
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=args.since_minutes)
    stmt = select(
        VisionDetection.label, func.count(VisionDetection.id)
    ).where(VisionDetection.created_at >= cutoff)
    if ctx.org_id is not None:
        stmt = stmt.where(VisionDetection.tenant_id == ctx.org_id)
    if args.drone_id:
        try:
            stmt = stmt.where(VisionDetection.drone_id == UUID(args.drone_id))
        except ValueError:
            return {"by_label": {}, "reason": "invalid drone_id"}
    stmt = stmt.group_by(VisionDetection.label)
    rows = (await ctx.db.execute(stmt)).all()
    by_label = {row[0]: int(row[1]) for row in rows}
    total = sum(by_label.values())
    top_label = max(by_label, key=by_label.get) if by_label else None
    return {
        "since_minutes": args.since_minutes,
        "total": total,
        "by_label": by_label,
        "top_label": top_label,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
ToolCallable = Callable[[ToolContext, BaseModel], Awaitable[dict[str, Any]]]


@dataclass
class ToolSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    func: ToolCallable
    permission: str = "readonly"  # "readonly" | "sensitive"


class ToolRegistry:
    """Simple in-memory registry keyed by tool name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get_specs(self) -> list[dict[str, Any]]:
        """Anthropic-style tool metadata for Function Calling."""
        out: list[dict[str, Any]] = []
        for spec in self._tools.values():
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.args_schema.model_json_schema(),
                }
            )
        return out

    async def call(
        self, tool_name: str, args: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        if tool_name not in self._tools:
            raise KeyError(f"unknown tool: {tool_name}")
        spec = self._tools[tool_name]
        parsed = spec.args_schema.model_validate(args or {})
        return await spec.func(ctx, parsed)


def build_default_registry() -> ToolRegistry:
    """Register the 6 read-only tools for Copilot v0.1."""
    r = ToolRegistry()
    r.register(
        ToolSpec(
            name="list_drones",
            description="List drones visible to the current org.",
            args_schema=ListDronesArgs,
            func=list_drones,  # type: ignore[arg-type]
        )
    )
    r.register(
        ToolSpec(
            name="get_drone_status",
            description="Get real-time status for a single drone by UUID.",
            args_schema=GetDroneStatusArgs,
            func=get_drone_status,  # type: ignore[arg-type]
        )
    )
    r.register(
        ToolSpec(
            name="check_airspace",
            description=(
                "Check whether a polygon or path intersects known no-fly "
                "zones. Placeholder implementation in v0.1."
            ),
            args_schema=CheckAirspaceArgs,
            func=check_airspace,  # type: ignore[arg-type]
        )
    )
    r.register(
        ToolSpec(
            name="query_weather",
            description="Query current weather conditions at a lat/lng.",
            args_schema=QueryWeatherArgs,
            func=query_weather,  # type: ignore[arg-type]
        )
    )
    r.register(
        ToolSpec(
            name="list_missions",
            description="List recent missions for the current org.",
            args_schema=ListMissionsArgs,
            func=list_missions,  # type: ignore[arg-type]
        )
    )
    r.register(
        ToolSpec(
            name="get_mission_detail",
            description="Get full detail (including waypoints) for a mission by UUID.",
            args_schema=GetMissionDetailArgs,
            func=get_mission_detail,  # type: ignore[arg-type]
        )
    )
    # ---- Sensitive mutation tools (approval-gated) -------------------
    r.register(
        ToolSpec(
            name="create_mission",
            description=(
                "Create a new flight mission with the given name, drone, and waypoints. "
                "Requires user approval before execution."
            ),
            args_schema=CreateMissionArgs,
            func=create_mission,  # type: ignore[arg-type]
            permission="sensitive",
        )
    )
    r.register(
        ToolSpec(
            name="dispatch_mission",
            description=(
                "Dispatch a planned mission — sends the flight plan to the assigned drone. "
                "Requires user approval before execution."
            ),
            args_schema=DispatchMissionArgs,
            func=dispatch_mission,  # type: ignore[arg-type]
            permission="sensitive",
        )
    )
    r.register(
        ToolSpec(
            name="abort_mission",
            description=(
                "Abort an in-progress mission. Requires user approval before execution."
            ),
            args_schema=AbortMissionArgs,
            func=abort_mission,  # type: ignore[arg-type]
            permission="sensitive",
        )
    )
    # ---- Vision AI query tools (T5.0) --------------------------------
    r.register(
        ToolSpec(
            name="list_detections",
            description=(
                "List recent vision AI detections, optionally filtered by drone, "
                "mission, label (e.g. 'person'), min_confidence, or trailing "
                "since_minutes window. Read-only, tenant-scoped."
            ),
            args_schema=ListDetectionsArgs,
            func=list_detections,  # type: ignore[arg-type]
        )
    )
    r.register(
        ToolSpec(
            name="detection_stats",
            description=(
                "Aggregate vision AI detection counts by class label over a "
                "trailing time window (default 60 min). Read-only. Use when the "
                "user asks 'how many people/vehicles have we seen recently?'"
            ),
            args_schema=DetectionStatsArgs,
            func=detection_stats,  # type: ignore[arg-type]
        )
    )
    return r


__all__ = [
    "ToolContext",
    "ToolRegistry",
    "ToolSpec",
    "build_default_registry",
    "list_drones",
    "get_drone_status",
    "check_airspace",
    "query_weather",
    "list_missions",
    "get_mission_detail",
    "create_mission",
    "dispatch_mission",
    "abort_mission",
    "list_detections",
    "detection_stats",
]
