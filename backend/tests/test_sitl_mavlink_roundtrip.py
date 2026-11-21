"""Real MAVLink v2 round-trip over UDP — no mocks, no PX4 binary required.

Starts ``sitl_mavlink_sim.py`` as a subprocess on a free UDP port, connects a
real pymavlink endpoint (and a real ``MavlinkConnector``), and verifies:

1. Telemetry IN: HEARTBEAT / GLOBAL_POSITION_INT frames decoded into a slot.
2. Command OUT + ACK IN: COMMAND_LONG(ARM) → COMMAND_ACK(result=ACCEPTED), and
   the simulator's state probe confirms it actually reacted (no HTTP旁路).
3. Mission handshake: full MISSION_COUNT → MISSION_REQUEST_INT →
   MISSION_ITEM_INT → MISSION_ACK flow via MissionDispatcher.

These tests exercise real bytes on a real socket with the real v20 dialect.
They bind loopback UDP/TCP only and finish within a few seconds.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SIM_SCRIPT = BACKEND / "scripts" / "sitl_mavlink_sim.py"


def _free_port(proto: int) -> int:
    kind = socket.SOCK_DGRAM if proto == "udp" else socket.SOCK_STREAM
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_sim(udp_port: int, state_port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["MAVLINK20"] = "1"
    env["PYTHONPATH"] = str(BACKEND)
    log = open(f"/tmp/sitl_roundtrip_{udp_port}.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, str(SIM_SCRIPT),
         "--system-id", "1", "--host", "127.0.0.1", "--port", str(udp_port),
         "--state-http-port", str(state_port), "--interval-ms", "100"],
        stdout=log, stderr=subprocess.STDOUT, env=env,
    )
    proc._sitl_log = log  # type: ignore[attr-defined]
    return proc


def _wait(cond, timeout: float = 8.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return False


def _probe_state(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/state", timeout=2
        ) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


@pytest.fixture
def sitl():
    udp = _free_port("udp")
    probe = _free_port("tcp")
    proc = _start_sim(udp, probe)
    try:
        assert proc.poll() is None, "sim exited immediately"
        assert _wait(lambda: _probe_state(probe) is not None, timeout=10), (
            f"sim state probe never came up; log="
            f"{open(proc._sitl_log.name, 'rb').read().decode(errors='replace')}"
        )
        yield udp, probe, proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            proc._sitl_log.close()
        except Exception:
            pass


def _open_conn(udp_port: int):
    from pymavlink import mavutil

    conn = mavutil.mavlink_connection(
        f"udpin:127.0.0.1:{udp_port}", source_system=255, dialect="common"
    )
    return conn


def test_real_telemetry_and_command_ack_roundtrip(sitl):
    """Telemetry in + COMMAND_LONG out + COMMAND_ACK in, all real MAVLink v2."""
    udp_port, probe_port, _proc = sitl
    from app.services.mavlink_connector import MavlinkConnector, load_sitl_config

    cfg = load_sitl_config()
    connector = MavlinkConnector(
        endpoint=f"udpin:127.0.0.1:{udp_port}", config=cfg
    )
    conn = connector.connect()
    try:
        # 1) Telemetry IN: decode frames with the real connector parser.
        got = {"hb": False, "pos": False}
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not (got["hb"] and got["pos"]):
            msg = conn.recv_match(blocking=True, timeout=1.0)
            if msg is None:
                continue
            connector.handle_message(msg)
            if msg.get_type() == "HEARTBEAT":
                got["hb"] = True
            if msg.get_type() == "GLOBAL_POSITION_INT":
                got["pos"] = True
        assert got["hb"] and got["pos"], f"telemetry not received: {got}"
        slot = connector.telemetry[1]
        assert abs(slot["lat"] - 22.8167) < 0.01, slot
        assert slot["mode"] is not None

        # 2) Command OUT + ACK IN via the connector's bidirectional helper.
        ack = connector.send_command_with_ack(
            target_system=1, command=400, params=(1.0, 0, 0, 0, 0, 0, 0),
            timeout_s=6.0,
        )
        assert ack["ok"] is True, ack
        assert ack["result"] == 0, ack

        # 3) Simulator state really changed — proves no HTTP bypass.
        state = _probe_state(probe_port)
        assert state is not None
        assert any(c["command"] == 400 for c in state["commands"]), state

        # 4) ACK recorded by the connector's parser path too.
        assert any(a.get("kind") == "COMMAND_ACK" for a in connector.acks)
    finally:
        conn.close()


def test_real_mission_upload_handshake(sitl):
    """Full MAVLink mission upload handshake against the simulator."""
    udp_port, probe_port, _proc = sitl
    from app.services.mission_dispatcher import MissionDispatcher

    conn = _open_conn(udp_port)
    try:
        # Wait for heartbeat so udpin learns the peer address before sending.
        hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=8)
        assert hb is not None and hb.get_srcSystem() == 1

        mission = SimpleNamespace(waypoints=[
            {"lat": 22.82, "lng": 108.32, "alt": 60.0},
            {"lat": 22.83, "lng": 108.33, "alt": 80.0},
        ])
        result = asyncio.run(
            MissionDispatcher(upload_timeout_s=8.0).dispatch_to_drone(
                mission, conn
            )
        )
        assert result["status"] == "dispatched", result
        assert result["mavlink_ack"] == "MAV_MISSION_ACCEPTED", result

        state = _probe_state(probe_port)
        assert state is not None
        assert len(state["mission_wps"]) == 2, state
        assert state["mode"] == "mission", state
    finally:
        conn.close()


def test_config_and_dialect_guard():
    """Config loads and declares the MAVLINK20=1 requirement explicitly."""
    from app.services.mavlink_connector import (
        load_sitl_config, reset_sitl_config_cache,
    )
    from app.services import mavlink_connector as mod

    reset_sitl_config_cache()
    cfg = load_sitl_config()
    assert cfg["version"] == "1.0"
    assert cfg["dialect"]["name"] == "common"
    assert cfg["dialect"]["require_mavlink20_env"] is True
    assert cfg["connector"]["command_ack_timeout_s"] == 2.0
    assert cfg["sitl"]["commands"]["arm"] == 400
    assert mod.DEFAULT_SITL_CONFIG.is_file()
