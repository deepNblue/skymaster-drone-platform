"""Copilot multi-turn context resolver — R21 Step G.

Adds entity/args carryover across turns so the operator can say things
like:

    T1: 让 D001 飞到 30.5, 104.06
    T2: 再飞高 20m           ← needs T1's lat/lng
    T3: 好的现在返航           ← needs T1's drone_id

Design principles
-----------------

1. **Deterministic + rule-based.** No LLM needed for coreference. We keep
   a compact ``ContextState`` (last drone_id, last waypoint, last mission,
   last altitude) and merge missing slots into the new turn's args when
   the parser leaves them empty.

2. **No silent drift.** If a turn *fully specifies* an entity, we
   over-write the context. If it merely omits, we back-fill. We never
   invent slots that were never seen.

3. **Bounded scope.** Context is per-session; it evaporates when the
   session ends. Configurable turn-window (default 5 turns) to avoid
   stale references (10 minutes ago ≠ "again").

4. **Explicit args.** The resolver returns an extra key ``resolved_from``
   listing which slots were carried over, so the UI can render "using
   drone D001 from turn #4".

Public surface
--------------

* ``load_context(db, session_id) -> ContextState``
* ``apply_context(parsed, ctx) -> ParsedIntent``  (returns a new object,
  never mutates input)
* ``update_context_from_turn(ctx, parsed) -> ContextState``  (pure)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.copilot_intent import ParsedIntent


CONTEXT_WINDOW_TURNS = 5


@dataclass
class ContextState:
    """Session-scoped Copilot context — small on purpose."""

    drone_id: Optional[str] = None
    mission_id: Optional[str] = None
    last_lat: Optional[float] = None
    last_lng: Optional[float] = None
    last_alt: Optional[float] = None
    last_intent: Optional[str] = None
    turn_idx: int = 0
    # 'resolved_from' chains — helpful for UI badges.
    slots_seen: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loading context from prior turns
# ---------------------------------------------------------------------------


async def load_context(
    db: AsyncSession, session_id: Any, *, window: int = CONTEXT_WINDOW_TURNS,
) -> ContextState:
    """Rebuild a session's context by scanning the last N turns in order.

    We do this on demand rather than persisting a snapshot so behaviour is
    always consistent with the actual turn log — a turn deletion or edit
    (rare, but possible) will not leave a stale context row.
    """
    from app.models.vision_copilot import CopilotTurnV2

    q = (
        select(CopilotTurnV2)
        .where(CopilotTurnV2.session_id == session_id)
        .order_by(CopilotTurnV2.turn_idx.asc())
    )
    rows = list((await db.execute(q)).scalars().all())
    rows = rows[-window:] if len(rows) > window else rows

    ctx = ContextState()
    for row in rows:
        _feed_row(ctx, row)
        ctx.turn_idx = max(ctx.turn_idx, row.turn_idx)
    return ctx


def _feed_row(ctx: ContextState, row: Any) -> None:
    args = row.args or {}
    ctx.last_intent = row.intent
    # tool_call carries the *fully-resolved* target — prefer it over args.
    tc = row.tool_call or {}
    tc_args = tc.get("args") or {}
    drone = tc.get("drone_id") or args.get("drone_id")
    if drone:
        ctx.drone_id = str(drone)
        ctx.slots_seen["drone_id"] = row.turn_idx
    mission = args.get("mission_id") or tc_args.get("mission_id")
    if mission:
        ctx.mission_id = str(mission)
        ctx.slots_seen["mission_id"] = row.turn_idx
    lat = _as_float(args.get("lat") or tc_args.get("lat"))
    lng = _as_float(args.get("lng") or tc_args.get("lng"))
    alt = _as_float(args.get("alt") or tc_args.get("alt"))
    if lat is not None:
        ctx.last_lat = lat
        ctx.slots_seen["lat"] = row.turn_idx
    if lng is not None:
        ctx.last_lng = lng
        ctx.slots_seen["lng"] = row.turn_idx
    if alt is not None:
        ctx.last_alt = alt
        ctx.slots_seen["alt"] = row.turn_idx


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Applying context to a new parse
# ---------------------------------------------------------------------------


def apply_context(parsed: ParsedIntent, ctx: ContextState) -> ParsedIntent:
    """Return a new ParsedIntent with missing slots filled from ``ctx``.

    Slots we currently carry over:
      * ``drone_id`` — for every command intent that implies a drone
      * ``lat``/``lng`` — for goto_waypoint referencing "再往那飞", "回那里"
      * ``alt`` — for "飞高一点", "再降 10m"
      * ``mission_id`` — for recording start/stop that referenced a mission
    """
    new_args = dict(parsed.args or {})
    resolved: list[str] = []

    # -- drone_id backfill (applies to every command intent) -------------
    if _needs_drone(parsed.intent) and not new_args.get("drone_id") and ctx.drone_id:
        new_args["drone_id"] = ctx.drone_id
        resolved.append("drone_id")

    # -- coordinates -----------------------------------------------------
    if parsed.intent == "goto_waypoint":
        if new_args.get("lat") is None and ctx.last_lat is not None:
            new_args["lat"] = ctx.last_lat
            resolved.append("lat")
        if new_args.get("lng") is None and ctx.last_lng is not None:
            new_args["lng"] = ctx.last_lng
            resolved.append("lng")

    # -- altitude carryover ---------------------------------------------
    #   Common cases:  "再飞高 20m" / "再降 10m" — parser will already have
    #   put a numeric ``alt_delta`` in args. We compute the absolute alt.
    delta = _as_float(new_args.get("alt_delta"))
    if delta is not None and ctx.last_alt is not None and new_args.get("alt") is None:
        new_args["alt"] = round(ctx.last_alt + delta, 3)
        resolved.append("alt(via delta)")
        # We keep alt_delta for auditing but the sim gets alt=absolute.
    elif new_args.get("alt") is None and ctx.last_alt is not None and _wants_alt(parsed.intent):
        # "再飞高" 无数量 → fall back to last altitude (no change but explicit)
        new_args["alt"] = ctx.last_alt
        resolved.append("alt")

    # -- mission_id backfill -------------------------------------------
    if parsed.intent in {"start_recording", "stop_recording"}:
        if not new_args.get("mission_id") and ctx.mission_id:
            new_args["mission_id"] = ctx.mission_id
            resolved.append("mission_id")

    if resolved:
        new_args["resolved_from"] = resolved
        # Bump confidence modestly when we successfully back-filled — the
        # rule parser initially had 0.6 for these ambiguous cases.
        new_conf = min(1.0, parsed.confidence + 0.15)
    else:
        new_conf = parsed.confidence

    return replace(parsed, args=new_args, confidence=new_conf)


def _needs_drone(intent: str) -> bool:
    return intent in {
        "takeoff", "land", "return_home", "hover", "goto_waypoint",
        "start_recording", "stop_recording", "status",
    }


def _wants_alt(intent: str) -> bool:
    # goto_waypoint already handles alt. Only 'change altitude' style
    # intents want a bare alt slot. Currently the rule parser has no
    # dedicated ``adjust_altitude`` intent, so this is a placeholder
    # for future coverage.
    return intent in {"goto_waypoint"}
