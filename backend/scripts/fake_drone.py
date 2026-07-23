"""FakeDrone — pure-Python MAVLink UDP generator for local development.

Sends realistic v0.1 telemetry so the MavlinkConnector → Redis → SQLite → WS
pipeline can be exercised without PX4 SITL, gazebo, or hardware.

Bi-directional command support
------------------------------
When ``--command-http PORT`` is set, FakeDrone runs a tiny HTTP server on
that port. The backend can POST commands there to trigger behaviour changes:

    POST /command
    {"type": "goto", "lat": 39.9, "lng": 116.4, "alt": 100}
    {"type": "mission", "waypoints": [{"lat":..,"lng":..,"alt":..}, ...]}
    {"type": "rtl"}                              # return to launch
    {"type": "arm"}   / {"type": "disarm"}

This is far simpler than negotiating MAVLink COMMAND_LONG round-trips over
UDP with pymavlink from a Python script, and it keeps the dev stack purely
in-process.

Usage
-----
    python scripts/fake_drone.py --system-id 1 --pattern circle
    python scripts/fake_drone.py --system-id 2 --port 14551 --pattern line
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, List, Optional

from pymavlink import mavutil  # type: ignore[import-untyped]
from pymavlink.dialects.v20 import common as mavlink  # type: ignore[import-untyped]

logger = logging.getLogger("fake_drone")


# --- Constants ---------------------------------------------------------------
_LATLON_SCALE = 1e7        # int deg * 1e7 per MAVLink common
_EARTH_R = 6_378_137.0     # meters (WGS84 equatorial)
_CIRCLE_RADIUS_M = 100.0
_CIRCLE_PERIOD_S = 60.0
_LINE_SPEED_MPS = 5.0

_HEARTBEAT_MS = 1000
_SYS_STATUS_MS = 500
_GPS_RAW_MS = 1000

# --- MAVLink command IDs (from common.xml) ----------------------------------
MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_NAV_TAKEOFF = 22
MAV_CMD_NAV_LAND = 21
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_COMPONENT_ARM_DISARM = 400
MAV_CMD_DO_SET_MODE = 176

# --- Drone state ------------------------------------------------------------
STATE_STANDBY = 3
STATE_ACTIVE = 4


@dataclass
class Position:
    lat: float
    lng: float
    alt: float          # meters MSL
    heading_deg: float  # 0..360
    speed_mps: float


@dataclass
class DroneState:
    """Mutable state that the command HTTP server can influence."""
    mode: str = "circle"         # circle | line | hover | goto | mission | rtl
    goto_target: Optional[Position] = None
    mission_wps: List[Position] = field(default_factory=list)
    mission_idx: int = 0
    home: Optional[Position] = None
    armed: bool = True


PatternFn = Callable[[float, argparse.Namespace, DroneState], Position]


def _pattern_hover(t: float, args: argparse.Namespace, _s: DroneState) -> Position:
    return Position(args.lat, args.lng, args.alt, 0.0, 0.0)


def _pattern_line(t: float, args: argparse.Namespace, _s: DroneState) -> Position:
    dx = _LINE_SPEED_MPS * t
    dlng = dx / (111_320.0 * math.cos(math.radians(args.lat)))
    return Position(args.lat, args.lng + dlng, args.alt, 90.0, _LINE_SPEED_MPS)


def _pattern_circle(t: float, args: argparse.Namespace, _s: DroneState) -> Position:
    theta = 2.0 * math.pi * (t % _CIRCLE_PERIOD_S) / _CIRCLE_PERIOD_S
    dx = _CIRCLE_RADIUS_M * math.cos(theta)
    dy = _CIRCLE_RADIUS_M * math.sin(theta)
    dlat = dy / 111_320.0
    dlng = dx / (111_320.0 * math.cos(math.radians(args.lat)))
    heading_math_rad = theta + math.pi / 2.0
    heading_compass = (90.0 - math.degrees(heading_math_rad)) % 360.0
    circ = 2.0 * math.pi * _CIRCLE_RADIUS_M
    speed = circ / _CIRCLE_PERIOD_S
    return Position(
        args.lat + dlat, args.lng + dlng, args.alt, heading_compass, speed
    )


def _fly_to(
    current: Position, target: Position, dt: float, max_speed: float = 15.0,
) -> Position:
    """Move ``current`` toward ``target`` by up to ``max_speed * dt`` meters."""
    dlat = target.lat - current.lat
    dlng = target.lng - current.lng
    dalt = target.alt - current.alt
    # Convert to meters (approx equirectangular).
    dy = dlat * 111_320.0
    dx = dlng * 111_320.0 * math.cos(math.radians(current.lat))
    dist = math.sqrt(dx * dx + dy * dy + dalt * dalt)
    step = min(dist, max_speed * dt)
    if dist < 0.5:
        return Position(target.lat, target.lng, target.alt, current.heading_deg, 0.0)
    frac = step / dist
    new_lat = current.lat + dlat * frac
    new_lng = current.lng + dlng * frac
    new_alt = current.alt + dalt * frac
    heading = (math.degrees(math.atan2(dx, dy))) % 360.0
    return Position(new_lat, new_lng, new_alt, heading, step / dt if dt > 0 else 0.0)


def _pattern_goto(
    t: float, args: argparse.Namespace, state: DroneState,
) -> Position:
    """Fly toward state.goto_target from wherever we currently are."""
    if state.goto_target is None:
        return _pattern_hover(t, args, state)
    current = getattr(state, "_last_pos", None) or Position(
        args.lat, args.lng, args.alt, 0.0, 0.0
    )
    dt = args.interval_ms / 1000.0
    new = _fly_to(current, state.goto_target, dt, max_speed=20.0)
    state._last_pos = new  # type: ignore[attr-defined]
    return new


def _pattern_mission(
    t: float, args: argparse.Namespace, state: DroneState,
) -> Position:
    """Fly the mission waypoint list sequentially, hover at final."""
    if not state.mission_wps:
        return _pattern_hover(t, args, state)
    if state.mission_idx >= len(state.mission_wps):
        # Mission complete — set state, hover at last waypoint.
        if not getattr(state, "_mission_completed_notified", False):
            state._mission_completed_notified = True  # type: ignore[attr-defined]
            state._mission_completed_at = time.time()  # type: ignore[attr-defined]
            logger.info("Mission COMPLETE — %d/%d", len(state.mission_wps), len(state.mission_wps))
        wp = state.mission_wps[-1]
        state._last_pos = wp  # type: ignore[attr-defined]
        return wp
    target = state.mission_wps[state.mission_idx]
    current = getattr(state, "_last_pos", None) or Position(
        args.lat, args.lng, args.alt, 0.0, 0.0
    )
    dt = args.interval_ms / 1000.0
    new = _fly_to(current, target, dt, max_speed=20.0)
    # Waypoint reached?
    dy = (target.lat - new.lat) * 111_320.0
    dx = (target.lng - new.lng) * 111_320.0 * math.cos(math.radians(new.lat))
    if math.sqrt(dx * dx + dy * dy) < 3.0 and abs(target.alt - new.alt) < 1.0:
        state.mission_idx += 1
        logger.info(
            "Mission waypoint %d/%d reached",
            state.mission_idx, len(state.mission_wps),
        )
    state._last_pos = new  # type: ignore[attr-defined]
    return new


def _pattern_rtl(
    t: float, args: argparse.Namespace, state: DroneState,
) -> Position:
    """Return to launch (home)."""
    if state.home is None:
        state.home = Position(args.lat, args.lng, args.alt, 0.0, 0.0)
    current = getattr(state, "_last_pos", None) or Position(
        args.lat, args.lng, args.alt, 0.0, 0.0
    )
    dt = args.interval_ms / 1000.0
    new = _fly_to(current, state.home, dt, max_speed=20.0)
    state._last_pos = new  # type: ignore[attr-defined]
    # Landed?
    dy = (state.home.lat - new.lat) * 111_320.0
    dx = (state.home.lng - new.lng) * 111_320.0 * math.cos(math.radians(new.lat))
    if math.sqrt(dx * dx + dy * dy) < 3.0:
        state.mode = "hover"
        logger.info("RTL complete, switching to hover")
    return new


_PATTERNS: dict[str, PatternFn] = {
    "hover": _pattern_hover,
    "line": _pattern_line,
    "circle": _pattern_circle,
    "goto": _pattern_goto,
    "mission": _pattern_mission,
    "rtl": _pattern_rtl,
}


# --- Main loop ---------------------------------------------------------------
class _Stop:
    """Tiny SIGINT/SIGTERM latch."""
    flag = False

    @classmethod
    def install(cls) -> None:
        def _handler(signum, frame):  # noqa: ARG001
            cls.flag = True
            logger.info("Received signal %s; stopping", signum)
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(s, _handler)
            except (ValueError, OSError):
                pass


class _CommandServer:
    """Tiny HTTP command endpoint bound to a DroneState."""

    def __init__(self, state: DroneState, args: argparse.Namespace, port: int):
        self.state = state
        self.args = args
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        state = self.state
        args = self.args

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *a):  # noqa: ARG002 — silence stdout spam
                logger.debug("cmd-http: " + fmt % a)

            def _json(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/state":
                    mission_completed = bool(
                        getattr(state, "_mission_completed_notified", False)
                    )
                    self._json(200, {
                        "mode": state.mode,
                        "armed": state.armed,
                        "mission_progress": (
                            f"{state.mission_idx}/{len(state.mission_wps)}"
                        ),
                        "mission_completed": mission_completed,
                        "mission_completed_at": (
                            getattr(state, "_mission_completed_at", None)
                        ),
                    })
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/command":
                    self._json(404, {"error": "not found"})
                    return
                length = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    self._json(400, {"error": "invalid json"})
                    return

                ctype = body.get("type", "").lower()
                if ctype == "goto":
                    state.mode = "goto"
                    state.goto_target = Position(
                        float(body["lat"]), float(body["lng"]),
                        float(body.get("alt", args.alt)),
                        0.0, 0.0,
                    )
                    logger.info("cmd: goto → %s", state.goto_target)
                elif ctype == "mission":
                    wps = [
                        Position(
                            float(w["lat"]), float(w["lng"]),
                            float(w.get("alt", args.alt)),
                            0.0, 0.0,
                        )
                        for w in body.get("waypoints", [])
                    ]
                    if not wps:
                        self._json(400, {"error": "waypoints empty"})
                        return
                    state.mission_wps = wps
                    state.mission_idx = 0
                    state.mode = "mission"
                    # Reset the completion marker for the new mission
                    state._mission_completed_notified = False  # type: ignore[attr-defined]
                    state._mission_completed_at = None  # type: ignore[attr-defined]
                    logger.info("cmd: mission with %d waypoints", len(wps))
                elif ctype == "rtl":
                    state.mode = "rtl"
                    logger.info("cmd: RTL")
                elif ctype in ("arm", "disarm"):
                    state.armed = (ctype == "arm")
                    logger.info("cmd: armed=%s", state.armed)
                elif ctype == "hover":
                    state.mode = "hover"
                elif ctype in ("circle", "line"):
                    state.mode = ctype
                else:
                    self._json(400, {"error": f"unknown command: {ctype}"})
                    return
                self._json(200, {"ok": True, "mode": state.mode})

        self.server = HTTPServer(("127.0.0.1", self.port), _Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="fake-drone-cmd", daemon=True,
        )
        self.thread.start()
        logger.info(
            "Command HTTP server listening on http://127.0.0.1:%d/command",
            self.port,
        )

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()


def _open_conn(host: str, port: int, system_id: int):
    """Open a pymavlink UDP-out connection tagged with our system id."""
    endpoint = f"udpout:{host}:{port}"
    conn = mavutil.mavlink_connection(
        endpoint, source_system=system_id, source_component=1
    )
    return conn


def _send_heartbeat(conn) -> None:
    conn.mav.heartbeat_send(
        type=mavlink.MAV_TYPE_QUADROTOR,
        autopilot=mavlink.MAV_AUTOPILOT_PX4,
        base_mode=209,       # ARMED | GUIDED | CUSTOM_MODE_ENABLED
        custom_mode=6,       # PX4 OFFBOARD (arbitrary but stable)
        system_status=mavlink.MAV_STATE_ACTIVE,
    )


def _send_global_position(conn, pos: Position, boot_ms: int) -> None:
    conn.mav.global_position_int_send(
        time_boot_ms=boot_ms,
        lat=int(pos.lat * _LATLON_SCALE),
        lon=int(pos.lng * _LATLON_SCALE),
        alt=int(pos.alt * 1000),               # mm MSL
        relative_alt=int(pos.alt * 1000),      # mm above home (== alt here)
        vx=0, vy=0, vz=0,                      # cm/s
        hdg=int(pos.heading_deg * 100),        # centidegrees
    )


def _send_vfr_hud(conn, pos: Position, throttle_pct: int) -> None:
    conn.mav.vfr_hud_send(
        airspeed=pos.speed_mps,
        groundspeed=pos.speed_mps,
        heading=int(pos.heading_deg),
        throttle=throttle_pct,
        alt=pos.alt,
        climb=0.0,
    )


def _send_attitude(conn, pos: Position, boot_ms: int) -> None:
    # Tiny wobble so downstream sees non-zero values.
    t = boot_ms / 1000.0
    roll = 0.05 * math.sin(t)
    pitch = 0.05 * math.cos(t)
    yaw = math.radians(pos.heading_deg)
    conn.mav.attitude_send(
        time_boot_ms=boot_ms,
        roll=roll, pitch=pitch, yaw=yaw,
        rollspeed=0.0, pitchspeed=0.0, yawspeed=0.0,
    )


def _send_sys_status(conn) -> None:
    conn.mav.sys_status_send(
        onboard_control_sensors_present=0,
        onboard_control_sensors_enabled=0,
        onboard_control_sensors_health=0,
        load=250,                 # 25.0% CPU
        voltage_battery=12000,    # mV
        current_battery=-1,       # unknown
        battery_remaining=85,     # %
        drop_rate_comm=0, errors_comm=0,
        errors_count1=0, errors_count2=0, errors_count3=0, errors_count4=0,
    )


def _send_gps_raw(conn, pos: Position, boot_ms: int) -> None:
    conn.mav.gps_raw_int_send(
        time_usec=boot_ms * 1000,
        fix_type=3,                                # 3D fix
        lat=int(pos.lat * _LATLON_SCALE),
        lon=int(pos.lng * _LATLON_SCALE),
        alt=int(pos.alt * 1000),
        eph=100, epv=100,                          # cm
        vel=int(pos.speed_mps * 100), cog=int(pos.heading_deg * 100),
        satellites_visible=12,
    )


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s[%(process)d] %(message)s",
    )
    _Stop.install()

    state = DroneState(mode=args.pattern, home=Position(
        args.lat, args.lng, args.alt, 0.0, 0.0
    ))
    conn = _open_conn(args.host, args.port, args.system_id)
    logger.info(
        "FakeDrone sysid=%d pattern=%s -> udpout:%s:%d (interval=%dms)",
        args.system_id, args.pattern, args.host, args.port, args.interval_ms,
    )

    cmd_server: Optional[_CommandServer] = None
    if args.command_http:
        cmd_server = _CommandServer(state, args, args.command_http)
        cmd_server.start()

    start = time.monotonic()
    next_pos_at = 0.0
    next_hb_at = 0.0
    next_sys_at = 0.0
    next_gps_at = 0.0
    next_stats_at = 5.0
    sent = 0
    tick = args.interval_ms / 1000.0

    while not _Stop.flag:
        now = time.monotonic() - start
        boot_ms = int(now * 1000)
        pattern_fn = _PATTERNS.get(state.mode, _pattern_hover)
        pos = pattern_fn(now, args, state)

        if now >= next_hb_at:
            _send_heartbeat(conn)
            sent += 1
            next_hb_at = now + (_HEARTBEAT_MS / 1000.0)

        if now >= next_pos_at:
            _send_global_position(conn, pos, boot_ms)
            _send_vfr_hud(conn, pos, throttle_pct=60)
            _send_attitude(conn, pos, boot_ms)
            sent += 3
            next_pos_at = now + tick

        if now >= next_sys_at:
            _send_sys_status(conn)
            sent += 1
            next_sys_at = now + (_SYS_STATUS_MS / 1000.0)

        if now >= next_gps_at:
            _send_gps_raw(conn, pos, boot_ms)
            sent += 1
            next_gps_at = now + (_GPS_RAW_MS / 1000.0)

        if now >= next_stats_at:
            logger.info(
                "sent %d messages · mode=%s · pos=(%.6f, %.6f, %.1fm)",
                sent, state.mode, pos.lat, pos.lng, pos.alt,
            )
            next_stats_at = now + 5.0

        upcoming = min(next_hb_at, next_pos_at, next_sys_at, next_gps_at)
        sleep_s = max(0.0, min(upcoming - (time.monotonic() - start), tick))
        time.sleep(sleep_s)

    logger.info("FakeDrone sysid=%d shutdown after %d messages", args.system_id, sent)
    if cmd_server:
        cmd_server.stop()
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="FakeDrone MAVLink generator")
    p.add_argument("--system-id", type=int, default=1, help="MAVLink system id")
    p.add_argument("--host", default="127.0.0.1", help="MAVLink UDP host")
    p.add_argument("--port", type=int, default=14550, help="MAVLink UDP port")
    p.add_argument(
        "--pattern", choices=list(_PATTERNS), default="circle",
        help="Flight pattern",
    )
    p.add_argument("--lat", type=float, default=39.9042)
    p.add_argument("--lng", type=float, default=116.4074)
    p.add_argument("--alt", type=float, default=100.0)
    p.add_argument("--interval-ms", type=int, default=100)
    p.add_argument(
        "--command-http", type=int, default=0,
        help="If >0, start an HTTP command server on this port",
    )
    return p
    return p


def main() -> int:
    args = _build_parser().parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
