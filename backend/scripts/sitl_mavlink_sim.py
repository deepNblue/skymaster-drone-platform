#!/usr/bin/env python3
"""Bidirectional MAVLink SITL simulator — real v2 frames, no PX4/Docker needed.

Unlike ``fake_drone.py`` (telemetry out + HTTP command旁路), this simulator
runs a **single bidirectional MAVLink UDP socket**: it streams real telemetry
frames AND receives COMMAND_LONG / MISSION_* frames, replying with COMMAND_ACK
and driving the mission upload handshake. The wire protocol is identical to a
real PX4 SITL, so switching to a real vehicle later needs no connector change.

Why this exists
---------------
* Local machine has pymavlink but no PX4 binary and no Docker integration.
* The gap in tests was: no real MAVLink bytes over a socket, no COMMAND_ACK.
* This closes that gap with a self-contained process driven by
  ``config/mavlink_sitl.json`` (zero hard-coded runtime parameters).

Critical gotcha: pymavlink only loads the v20 dialect (which carries
COMMAND_ACK.target_system etc.) when ``MAVLINK20=1`` is set BEFORE importing
mavutil. We force it at module import, matching the config declaration.

Usage
-----
    python scripts/sitl_mavlink_sim.py --system-id 1 --port 14550
    python scripts/sitl_mavlink_sim.py --state-http-port 15901  # optional probe

The backend connector binds ``udpin:0.0.0.0:<port>``; this simulator connects
to it with ``udpout`` and reads commands back on the same socket (pymavlink's
udpin remembers the last peer and can send to it).
"""
from __future__ import annotations

# MUST precede any pymavlink import: selects v20 dialect / MAVLink2 wire.
import os

os.environ["MAVLINK20"] = "1"

import argparse
import json
import logging
import math
import signal
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from pymavlink import mavutil  # type: ignore[import-untyped]
from pymavlink.dialects.v20 import common as mavlink  # type: ignore[import-untyped]

logger = logging.getLogger("sitl_mavlink_sim")

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "mavlink_sitl.json"
_LATLON_SCALE = 1e7


# ---------------------------------------------------------------------------
# Config (all runtime parameters; code has no hard-coded protocol numbers)
# ---------------------------------------------------------------------------


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path or os.getenv("MAVLINK_SITL_CONFIG") or DEFAULT_CONFIG)
    with cfg_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class SitlState:
    armed: bool = True
    mode: str = "circle"          # circle | hover | mission | rtl | takeoff
    custom_mode: int = 6
    lat: float = 0.0
    lng: float = 0.0
    alt: float = 0.0
    heading: float = 0.0
    speed: float = 0.0
    throttle: int = 60
    mission_wps: list[dict[str, float]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    mission_count: int | None = None
    mission_received: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "armed": self.armed, "mode": self.mode,
                "custom_mode": self.custom_mode,
                "lat": self.lat, "lng": self.lng, "alt": self.alt,
                "heading": self.heading, "speed": self.speed,
                "mission_wps": list(self.mission_wps),
                "mission_count": self.mission_count,
                "mission_received": self.mission_received,
                "commands": list(self.commands),
            }


_STOP = threading.Event()


class _StateServer:
    """Optional HTTP probe so tests can assert the simulator really reacted."""

    def __init__(self, state: SitlState, port: int) -> None:
        self.state = state
        self.port = port
        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = json.dumps(state.snapshot(), ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: Any) -> None:
                pass

        self._httpd = HTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("State probe http://127.0.0.1:%d/state", self.port)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()


# ---------------------------------------------------------------------------
# Telemetry senders
# ---------------------------------------------------------------------------


def _send_heartbeat(conn: Any, state: SitlState, cfg: dict[str, Any]) -> None:
    s = cfg["sitl"]
    conn.mav.heartbeat_send(
        type=s["vehicle_type"], autopilot=s["autopilot"],
        base_mode=s["base_mode"], custom_mode=state.custom_mode,
        system_status=s["system_status"], mavlink_version=s["mavlink_version"],
    )


def _send_position(conn: Any, state: SitlState, boot_ms: int) -> None:
    with state.lock:
        lat, lng, alt = state.lat, state.lng, state.alt
        heading, speed, throttle = state.heading, state.speed, state.throttle
    conn.mav.global_position_int_send(
        time_boot_ms=boot_ms,
        lat=int(lat * _LATLON_SCALE), lon=int(lng * _LATLON_SCALE),
        alt=int(alt * 1000), relative_alt=int(alt * 1000),
        vx=0, vy=0, vz=0, hdg=int(heading * 100),
    )
    conn.mav.vfr_hud_send(
        airspeed=speed, groundspeed=speed, heading=int(heading),
        throttle=throttle, alt=alt, climb=0.0,
    )
    t = boot_ms / 1000.0
    conn.mav.attitude_send(
        time_boot_ms=boot_ms,
        roll=0.05 * math.sin(t), pitch=0.05 * math.cos(t),
        yaw=math.radians(heading),
        rollspeed=0.0, pitchspeed=0.0, yawspeed=0.0,
    )


def _send_sys_status(conn: Any) -> None:
    conn.mav.sys_status_send(
        onboard_control_sensors_present=0, onboard_control_sensors_enabled=0,
        onboard_control_sensors_health=0, load=250, voltage_battery=12000,
        current_battery=-1, battery_remaining=85, drop_rate_comm=0,
        errors_comm=0, errors_count1=0, errors_count2=0,
        errors_count3=0, errors_count4=0,
    )


def _send_gps(conn: Any, state: SitlState, boot_ms: int) -> None:
    with state.lock:
        lat, lng, alt, heading, speed = (
            state.lat, state.lng, state.alt, state.heading, state.speed
        )
    conn.mav.gps_raw_int_send(
        time_usec=boot_ms * 1000, fix_type=3,
        lat=int(lat * _LATLON_SCALE), lon=int(lng * _LATLON_SCALE),
        alt=int(alt * 1000), eph=100, epv=100,
        vel=int(speed * 100), cog=int(heading * 100), satellites_visible=12,
    )


# ---------------------------------------------------------------------------
# Command handling (the missing half of the link)
# ---------------------------------------------------------------------------


def _ack(conn: Any, command: int, cmd: dict[str, Any], cfg: dict[str, Any]) -> None:
    conn.mav.command_ack_send(
        command, cfg["sitl"]["ack_result_accepted"], 0, 0,
        cmd.get("src_system", 1), cmd.get("src_component", 1),
    )


def handle_inbound(conn: Any, msg: Any, state: SitlState, cfg: dict[str, Any]) -> None:
    """Process one inbound COMMAND_LONG / MISSION_* frame and reply on-wire."""
    if msg is None:
        return
    mtype = msg.get_type()
    cmds = cfg["sitl"]["commands"]
    src_sys = msg.get_srcSystem() if hasattr(msg, "get_srcSystem") else 1
    src_comp = msg.get_srcComponent() if hasattr(msg, "get_srcComponent") else 1

    if mtype == "COMMAND_LONG":
        command = int(msg.command)
        entry = {
            "command": command, "param1": msg.param1,
            "src_system": src_sys, "src_component": src_comp, "at": time.time(),
        }
        with state.lock:
            state.commands.append(entry)
            if command == cmds["arm"]:
                state.armed = bool(msg.param1 >= 1)
                state.throttle = 60 if state.armed else 0
            elif command == cmds["set_mode"]:
                state.custom_mode = int(msg.param1)
                state.mode = {cmds["px4_mode_auto"]: "mission",
                              cmds["px4_mode_rtl"]: "rtl"}.get(
                    state.custom_mode, "circle"
                )
            elif command == cmds["rtl"]:
                state.mode = "rtl"
                state.custom_mode = cmds["px4_mode_rtl"]
            elif command == cmds["mission_start"]:
                state.mode = "mission"
                state.custom_mode = cmds["px4_mode_auto"]
                state.mission_idx = 0
            elif command == cmds["takeoff"]:
                state.mode = "takeoff"
        _ack(conn, command, entry, cfg)
        logger.info("COMMAND_LONG cmd=%d p1=%.1f from sys=%d → ACK accepted",
                    command, msg.param1, src_sys)

    elif mtype == "MISSION_COUNT":
        with state.lock:
            state.mission_count = int(msg.count)
            state.mission_received = 0
            state.mission_wps = []
        # Request every waypoint; dispatcher replies one MISSION_ITEM_INT each.
        for seq in range(state.mission_count):
            conn.mav.mission_request_int_send(src_sys, src_comp, seq, 0)
        logger.info("MISSION_COUNT=%d → sent %d MISSION_REQUEST_INT",
                    state.mission_count, state.mission_count)

    elif mtype == "MISSION_ITEM_INT":
        with state.lock:
            state.mission_wps.append({
                "lat": msg.x / _LATLON_SCALE, "lng": msg.y / _LATLON_SCALE,
                "alt": float(msg.z), "seq": int(msg.seq),
            })
            state.mission_received += 1
            done = (state.mission_count is not None
                    and state.mission_received >= state.mission_count)
        if done:
            conn.mav.mission_ack_send(
                src_sys, src_comp, cfg["sitl"]["ack_result_accepted"], 0
            )
            logger.info("MISSION_ITEM_INT all received (%d) → MISSION_ACK accepted",
                        state.mission_received)


def command_loop(conn: Any, state: SitlState, cfg: dict[str, Any]) -> None:
    """Read inbound MAVLink frames on the same socket we stream telemetry on."""
    while not _STOP.is_set():
        try:
            msg = conn.recv_match(blocking=True, timeout=0.5)
            handle_inbound(conn, msg, state, cfg)
        except Exception:  # noqa: BLE001 — keep the sim alive
            logger.exception("command_loop tick failed")


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------


def _step_position(elapsed: float, state: SitlState, cfg: dict[str, Any]) -> None:
    move = cfg["sitl"]["movement"]
    home = cfg["sitl"]["home"]
    with state.lock:
        mode = state.mode
        if mode == "mission" and state.mission_wps:
            idx = min(int(elapsed / 3), len(state.mission_wps) - 1)
            wp = state.mission_wps[idx]
            state.lat, state.lng, state.alt = wp["lat"], wp["lng"], wp["alt"]
            state.heading = (state.heading + 1.0) % 360
            state.speed = move["speed_mps"]
        elif mode == "rtl":
            state.lat += (home["lat"] - state.lat) * 0.02
            state.lng += (home["lng"] - state.lng) * 0.02
            state.alt = max(home["alt_m"], state.alt - move["climb_step_m"] * 0.02)
            state.heading = (state.heading + 2.0) % 360
            state.speed = move["speed_mps"]
        elif mode == "takeoff":
            state.alt += move["climb_step_m"] * 0.05
            state.speed = 0.0
        else:  # circle / hover
            if mode == "circle":
                r = move["circle_radius_m"]
                angle = elapsed * move["speed_mps"] / max(r, 1.0)
                dlat = (r / 111320.0) * math.cos(angle)
                dlng = (r / (111320.0 * math.cos(math.radians(home["lat"])))) * math.sin(angle)
                state.lat, state.lng = home["lat"] + dlat, home["lng"] + dlng
                state.heading = (math.degrees(angle) + 90) % 360
                state.speed = move["speed_mps"]
            else:
                state.lat, state.lng, state.alt = home["lat"], home["lng"], home["alt_m"]
                state.speed = 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s[%(process)d] %(message)s",
    )
    cfg = load_config(args.config)
    if cfg["dialect"].get("require_mavlink20_env") and os.getenv("MAVLINK20") != "1":
        raise RuntimeError("MAVLINK20=1 required for v20 COMMAND_ACK fields")

    sitl = cfg["sitl"]
    tel = cfg["telemetry"]
    host = args.host or sitl["default_host"]
    port = args.port if args.port is not None else sitl["default_port"]
    state = SitlState(
        lat=args.lat if args.lat is not None else sitl["home"]["lat"],
        lng=args.lng if args.lng is not None else sitl["home"]["lng"],
        alt=args.alt if args.alt is not None else sitl["home"]["alt_m"],
        custom_mode=sitl["custom_mode"],
    )

    conn = mavutil.mavlink_connection(
        f"udpout:{host}:{port}",
        source_system=args.system_id,
        source_component=args.component_id,
        dialect=cfg["dialect"]["name"],
    )
    logger.info(
        "SITL sysid=%d udpout:%s:%d dialect=%s wire=%s (bidirectional)",
        args.system_id, host, port,
        cfg["dialect"]["name"], cfg["dialect"]["wire_protocol"],
    )

    threading.Thread(
        target=command_loop, args=(conn, state, cfg), daemon=True
    ).start()

    probe_port = args.state_http_port
    if probe_port is None:
        env_name = sitl["state_http_port_env"]
        probe_port = int(os.getenv(env_name) or sitl["state_http_port"] or 0)
    probe = _StateServer(state, probe_port) if probe_port else None
    if probe:
        probe.start()

    def _on_signal(_signum: int, _frame: Any) -> None:
        _STOP.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _on_signal)

    start = time.monotonic()
    next_hb = next_sys = next_gps = next_stats = 0.0
    tick = args.interval_ms / 1000.0
    while not _STOP.is_set():
        now = time.monotonic() - start
        boot_ms = int(now * 1000)
        _step_position(now, state, cfg)
        if now >= next_hb:
            _send_heartbeat(conn, state, cfg)
            next_hb = now + tel["heartbeat_period_ms"] / 1000.0
        if now >= next_sys:
            _send_sys_status(conn)
            next_sys = now + tel["sys_status_period_ms"] / 1000.0
        if now >= next_gps:
            _send_gps(conn, state, boot_ms)
            next_gps = now + tel["gps_period_ms"] / 1000.0
        # position every tick
        _send_position(conn, state, boot_ms)
        if now >= next_stats:
            s = state.snapshot()
            logger.info("telemetry alive · mode=%s armed=%s pos=(%.6f,%.6f,%.1fm) wps=%d",
                        s["mode"], s["armed"], s["lat"], s["lng"], s["alt"],
                        len(s["mission_wps"]))
            next_stats = now + sitl["log_interval_ms"] / 1000.0
        time.sleep(tick)

    if probe:
        probe.stop()
    conn.close()
    logger.info("SITL shutdown cleanly")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bidirectional MAVLink SITL simulator")
    p.add_argument("--config", help="Override config path (env MAVLINK_SITL_CONFIG)")
    p.add_argument("--system-id", type=int, default=None)
    p.add_argument("--component-id", type=int, default=None)
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--lat", type=float, default=None)
    p.add_argument("--lng", type=float, default=None)
    p.add_argument("--alt", type=float, default=None)
    p.add_argument("--interval-ms", type=int, default=None)
    p.add_argument("--state-http-port", type=int, default=None)
    return p


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_config(args.config)
    sitl, tel = cfg["sitl"], cfg["telemetry"]
    if args.system_id is None:
        args.system_id = sitl["default_system_id"]
    if args.component_id is None:
        args.component_id = sitl["default_component_id"]
    if args.interval_ms is None:
        args.interval_ms = tel["position_period_ms"]
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
