"""Mission dispatcher — validates and uploads waypoint missions to a drone via MAVLink.

SkyMaster v0.1 mission-dispatch flow:
1. Client POSTs /missions/{id}/dispatch.
2. API resolves the target drone's MavlinkConnector from ConnectionManager.
3. Dispatcher validates the mission (coord bounds, altitude bounds).
4. Dispatcher performs the MAVLink mission upload handshake:
       MISSION_COUNT  -> drone
       MISSION_REQUEST(_INT) <- drone (per waypoint)
       MISSION_ITEM_INT -> drone
       MISSION_ACK <- drone
5. On ACK == MAV_MISSION_ACCEPTED, dispatcher sends MAV_CMD_MISSION_START.
6. abort() sends MAV_CMD_NAV_RETURN_TO_LAUNCH.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

try:  # soft import — tests can run without pymavlink installed
    from pymavlink import mavutil, mavwp  # type: ignore[import-untyped]
    from pymavlink.dialects.v20 import common as mavlink_common  # type: ignore
except ImportError:  # pragma: no cover
    mavutil = None  # type: ignore[assignment]
    mavwp = None  # type: ignore[assignment]
    mavlink_common = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# MAVLink constants (mirrored for readability / test isolation) -------------
MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_MISSION_START = 300
MAV_FRAME_GLOBAL_RELATIVE_ALT_INT = 3
MAV_MISSION_ACCEPTED = 0

# Named ACK codes for human-readable log/return values.
_MISSION_ACK_NAMES: dict[int, str] = {
    0: "MAV_MISSION_ACCEPTED",
    1: "MAV_MISSION_ERROR",
    2: "MAV_MISSION_UNSUPPORTED_FRAME",
    3: "MAV_MISSION_UNSUPPORTED",
    4: "MAV_MISSION_NO_SPACE",
    5: "MAV_MISSION_INVALID",
    6: "MAV_MISSION_INVALID_PARAM1",
    7: "MAV_MISSION_INVALID_PARAM2",
    8: "MAV_MISSION_INVALID_PARAM3",
    9: "MAV_MISSION_INVALID_PARAM4",
    10: "MAV_MISSION_INVALID_PARAM5_X",
    11: "MAV_MISSION_INVALID_PARAM6_Y",
    12: "MAV_MISSION_INVALID_PARAM7",
    13: "MAV_MISSION_INVALID_SEQUENCE",
    14: "MAV_MISSION_DENIED",
    15: "MAV_MISSION_OPERATION_CANCELLED",
}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


class MissionDispatcher:
    """Stateless helper that validates and uploads missions to a drone."""

    def __init__(
        self,
        upload_timeout_s: float = 30.0,
        target_system: int = 1,
        target_component: int = 1,
    ) -> None:
        self.upload_timeout_s = upload_timeout_s
        self.target_system = target_system
        self.target_component = target_component

    # ------------------------------------------------------------ validation
    async def validate_mission(self, mission: Any) -> ValidationResult:
        """Sanity-check a mission's waypoints before we touch the radio."""
        result = ValidationResult(ok=True)

        waypoints: Iterable[dict[str, Any]] | None = getattr(
            mission, "waypoints", None
        )
        if not waypoints:
            result.ok = False
            result.errors.append("mission has no waypoints")
            return result

        for idx, wp in enumerate(waypoints):
            lat = wp.get("lat")
            lng = wp.get("lng")
            alt = wp.get("alt")

            if lat is None or lng is None or alt is None:
                result.ok = False
                result.errors.append(
                    f"waypoint[{idx}] missing lat/lng/alt (got {wp!r})"
                )
                continue

            try:
                lat_f = float(lat)
                lng_f = float(lng)
                alt_f = float(alt)
            except (TypeError, ValueError):
                result.ok = False
                result.errors.append(
                    f"waypoint[{idx}] has non-numeric coord/alt: {wp!r}"
                )
                continue

            if not (-90.0 <= lat_f <= 90.0):
                result.ok = False
                result.errors.append(
                    f"waypoint[{idx}].lat={lat_f} out of range [-90, 90]"
                )
            if not (-180.0 <= lng_f <= 180.0):
                result.ok = False
                result.errors.append(
                    f"waypoint[{idx}].lng={lng_f} out of range [-180, 180]"
                )
            if not (0.0 <= alt_f <= 500.0):
                result.ok = False
                result.errors.append(
                    f"waypoint[{idx}].alt={alt_f} out of range [0, 500] m AGL"
                )
            elif alt_f > 120.0:
                result.warnings.append(
                    f"waypoint[{idx}].alt={alt_f} m exceeds typical 120 m "
                    "civilian AGL ceiling; confirm regulatory clearance"
                )

        return result

    # ------------------------------------------------------------- upload
    def _build_wp_loader(
        self, waypoints: list[dict[str, Any]]
    ) -> Any:
        """Convert JSON waypoints into a pymavlink MAVWPLoader (when available)."""
        if mavwp is None or mavlink_common is None:  # pragma: no cover
            return None

        loader = mavwp.MAVWPLoader()
        for seq, wp in enumerate(waypoints):
            item = mavlink_common.MAVLink_mission_item_int_message(
                target_system=self.target_system,
                target_component=self.target_component,
                seq=seq,
                frame=MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                command=MAV_CMD_NAV_WAYPOINT,
                current=1 if seq == 0 else 0,
                autocontinue=1,
                param1=0.0,  # hold time
                param2=float(wp.get("accept_radius", 2.0)),
                param3=0.0,  # pass radius
                param4=float("nan"),  # yaw
                x=int(round(float(wp["lat"]) * 1e7)),
                y=int(round(float(wp["lng"]) * 1e7)),
                z=float(wp["alt"]),
            )
            loader.add(item)
        return loader

    async def dispatch_to_drone(
        self, mission: Any, mavlink_conn: Any
    ) -> dict[str, Any]:
        """Upload the mission and send MISSION_START.

        ``mavlink_conn`` must expose a ``mav`` attribute (pymavlink connection
        API) and ``recv_match(...)``.
        """
        waypoints = list(getattr(mission, "waypoints", []) or [])
        if not waypoints:
            return {
                "status": "failed",
                "mavlink_ack": None,
                "error": "no waypoints to dispatch",
            }

        # Build items (loader is optional; we always send raw MISSION_ITEM_INT).
        self._build_wp_loader(waypoints)

        loop = asyncio.get_running_loop()

        try:
            # 1. MISSION_COUNT
            await loop.run_in_executor(
                None,
                lambda: mavlink_conn.mav.mission_count_send(
                    self.target_system,
                    self.target_component,
                    len(waypoints),
                ),
            )
            logger.info(
                "MISSION_COUNT sent (count=%d) to sys=%d",
                len(waypoints), self.target_system,
            )

            # 2. For each expected MISSION_REQUEST(_INT), reply with MISSION_ITEM_INT.
            for seq, wp in enumerate(waypoints):
                req = await loop.run_in_executor(
                    None,
                    lambda: mavlink_conn.recv_match(
                        type=["MISSION_REQUEST", "MISSION_REQUEST_INT"],
                        blocking=True,
                        timeout=self.upload_timeout_s,
                    ),
                )
                if req is None:
                    return {
                        "status": "failed",
                        "mavlink_ack": None,
                        "error": f"timeout waiting for MISSION_REQUEST seq={seq}",
                    }
                req_seq = getattr(req, "seq", seq)
                if req_seq != seq:
                    logger.warning(
                        "Drone requested seq=%d but next-in-order is %d; honoring request",
                        req_seq, seq,
                    )

                target_wp = waypoints[req_seq]
                await loop.run_in_executor(
                    None,
                    lambda tw=target_wp, s=req_seq: mavlink_conn.mav.mission_item_int_send(
                        self.target_system,
                        self.target_component,
                        s,
                        MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                        MAV_CMD_NAV_WAYPOINT,
                        1 if s == 0 else 0,        # current
                        1,                          # autocontinue
                        0.0,                        # param1 hold time
                        float(tw.get("accept_radius", 2.0)),
                        0.0,                        # pass radius
                        float("nan"),               # yaw
                        int(round(float(tw["lat"]) * 1e7)),
                        int(round(float(tw["lng"]) * 1e7)),
                        float(tw["alt"]),
                    ),
                )

            # 3. Await MISSION_ACK
            ack = await loop.run_in_executor(
                None,
                lambda: mavlink_conn.recv_match(
                    type="MISSION_ACK",
                    blocking=True,
                    timeout=self.upload_timeout_s,
                ),
            )
            if ack is None:
                return {
                    "status": "failed",
                    "mavlink_ack": None,
                    "error": "timeout waiting for MISSION_ACK",
                }

            ack_type = getattr(ack, "type", None)
            ack_name = _MISSION_ACK_NAMES.get(ack_type, f"UNKNOWN({ack_type})")

            if ack_type != MAV_MISSION_ACCEPTED:
                return {
                    "status": "failed",
                    "mavlink_ack": ack_name,
                    "error": f"drone rejected mission: {ack_name}",
                }

            # 4. MAV_CMD_MISSION_START
            await loop.run_in_executor(
                None,
                lambda: mavlink_conn.mav.command_long_send(
                    self.target_system,
                    self.target_component,
                    MAV_CMD_MISSION_START,
                    0,                # confirmation
                    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                ),
            )
            logger.info("MISSION_START sent to sys=%d", self.target_system)

            return {
                "status": "dispatched",
                "mavlink_ack": ack_name,
                "error": None,
            }

        except Exception as exc:  # noqa: BLE001 — surface to caller
            logger.exception("dispatch_to_drone failed")
            return {
                "status": "failed",
                "mavlink_ack": None,
                "error": str(exc),
            }

    # ---------------------------------------------------------------- abort
    async def abort(self, mavlink_conn: Any) -> dict[str, Any]:
        """Command Return-To-Launch on the target drone."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: mavlink_conn.mav.command_long_send(
                    self.target_system,
                    self.target_component,
                    MAV_CMD_NAV_RETURN_TO_LAUNCH,
                    0,
                    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                ),
            )
            logger.info("RTL sent to sys=%d", self.target_system)
            return {"status": "aborted", "error": None}
        except Exception as exc:  # noqa: BLE001
            logger.exception("abort failed")
            return {"status": "failed", "error": str(exc)}
