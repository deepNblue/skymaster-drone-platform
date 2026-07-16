"""Copilot Command Bus — R21 Step B.

Bridges parsed Copilot intents into the platform's actual command
endpoints. Deliberately narrow surface:

  * ``execute_tool_call(call, *, actor, request)`` — dispatch a **safe subset**
    of tool calls the intent parser can produce.

Design principles
-----------------

1. **Never invoke a tool the caller lacks permission for.**  Every drone
   command requires ``operator`` role at minimum. Any elevation to
   ``admin``-only ops is refused with 403.
2. **Never invent side effects.** We only wrap endpoints that already exist
   (``/sim/drones/{sysid}/...`` for now; production adds MAVLink command
   bus via the mission ORM).
3. **Never crash the Copilot loop.** Failed executions return a structured
   ``{status: "error", detail: "..."}`` — the turn is still stored, the
   operator sees the error inline in chat.
4. **Read-only Copilot by default.**  ``execute=True`` must be explicitly
   supplied by the API caller; unset defaults to plan-only.

The bus is intentionally *not* a Celery/Redis abstraction — it is a thin
function-level router. Multi-drone fleets and MAVLink command_long will
plug in later via the same interface.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from app.models.user import User

log = logging.getLogger(__name__)


# Tool → (sim endpoint suffix, body-transform) mapping.
# The transform receives (args) and returns a dict body (or None if the sim
# endpoint takes no body).
_SIM_ROUTE: dict[str, tuple[str, Any]] = {
    "drone.command.takeoff":       ("arm", None),  # takeoff = arm + auto ascent on FakeDrone
    "drone.command.land":          ("mode", lambda a: {"mode": "hover"}),  # closest sim analog
    "drone.command.rth":           ("rtl", None),
    "drone.command.hover":         ("mode", lambda a: {"mode": "hover"}),
    "drone.command.goto":          ("goto", lambda a: {
        "lat": float(a["lat"]),
        "lng": float(a["lng"]),
        "alt": float(a.get("alt") or 50.0),
    }),
    "mission.recording.start":     (None, None),   # not wired to sim yet
    "mission.recording.stop":      (None, None),
    "vision.detections.recent":    (None, None),   # handled in-process, no HTTP
    "agent.status":                (None, None),
}


# Roles that may execute drone control tools.
_ALLOWED_ROLES = {"operator", "admin"}


def _sim_port_for(drone_id: str | None) -> int | None:
    """Resolve a drone_id → FakeDrone HTTP command port.

    Precedence:
      * ``COPILOT_SIM_PORT_MAP`` env var: JSON dict ``{"<drone_id>":15001,...}``
      * Fallback: first entry of ``SIM_DRONES`` (``1:15001,2:15002``)

    Missing mapping → None (bus reports 'no route').
    """
    if not drone_id:
        # No specific drone → try the first sim drone.
        raw = os.getenv("SIM_DRONES", "")
        first = raw.split(",", 1)[0].strip()
        if ":" in first:
            try:
                return int(first.split(":", 1)[1])
            except ValueError:
                return None
        return None

    override = os.getenv("COPILOT_SIM_PORT_MAP", "").strip()
    if override:
        try:
            mapping = json.loads(override)
            if drone_id in mapping:
                return int(mapping[drone_id])
        except Exception as exc:  # pragma: no cover
            log.warning("COPILOT_SIM_PORT_MAP not JSON: %s", exc)
    return None


def _post_sim(port: int, endpoint: str, body: dict | None) -> dict:
    """POST to the FakeDrone HTTP server. Returns structured result."""
    url = f"http://127.0.0.1:{port}/{endpoint}"
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode())
            return {"status": "ok", "sim_response": payload, "endpoint": endpoint}
    except urllib.error.HTTPError as exc:
        return {"status": "error", "detail": f"sim rejected: HTTP {exc.code} {exc.reason}"}
    except urllib.error.URLError as exc:
        return {"status": "error", "detail": f"sim unreachable :{port} — {exc.reason}"}
    except Exception as exc:
        return {"status": "error", "detail": f"unexpected: {exc.__class__.__name__}: {exc}"}


def is_executable(tool: str) -> bool:
    """Whether the bus has a route for the given tool name."""
    route = _SIM_ROUTE.get(tool)
    return bool(route and route[0])


def execute_tool_call(
    call: dict[str, Any],
    *,
    actor: User,
    drone_id: str | None = None,
) -> dict[str, Any]:
    """Execute a planned Copilot tool call.

    Returns a dict with at least ``status`` in {ok, error, denied, noop}.
    Never raises.
    """
    if not call or not isinstance(call, dict):
        return {"status": "noop", "detail": "no tool_call"}

    tool = call.get("tool")
    if not tool:
        return {"status": "noop", "detail": "empty tool"}

    # 1) Role gate — Copilot never elevates the caller.
    role = getattr(actor, "role", None)
    if role not in _ALLOWED_ROLES:
        return {
            "status": "denied",
            "detail": f"role {role!r} 无权执行 Copilot 指令，需 operator/admin",
        }

    # 2) Route lookup.
    route = _SIM_ROUTE.get(tool)
    if not route or not route[0]:
        # Known tool but no sim route → return a "planned" marker so the UI
        # can still show it. Do NOT surface an error to the operator.
        return {"status": "planned", "detail": f"{tool} 未接入执行总线（v0.1 保留）"}

    endpoint, body_fn = route
    target_drone = drone_id or call.get("drone_id")
    port = _sim_port_for(target_drone)
    if port is None:
        return {
            "status": "error",
            "detail": (
                f"未找到 drone_id={target_drone!r} 的执行端口。"
                "请配置 SIM_DRONES 或 COPILOT_SIM_PORT_MAP。"
            ),
        }

    body = body_fn(call.get("args") or {}) if body_fn else None
    return _post_sim(port, endpoint, body)
