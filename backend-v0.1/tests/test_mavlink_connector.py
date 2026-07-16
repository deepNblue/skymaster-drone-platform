"""Unit tests for the MAVLink connector — no sockets, no Redis."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _msg(mtype: str, sysid: int = 1, **fields) -> SimpleNamespace:
    """Build a fake pymavlink message with a ``get_type`` / ``get_srcSystem``."""
    ns = SimpleNamespace(**fields)
    ns.get_type = lambda: mtype  # type: ignore[attr-defined]
    ns.get_srcSystem = lambda: sysid  # type: ignore[attr-defined]
    return ns


def test_global_position_int_parsing() -> None:
    with patch(
        "app.services.mavlink_connector.mavutil.mavlink_connection",
        return_value=MagicMock(),
    ):
        from app.services.mavlink_connector import MavlinkConnector

        c = MavlinkConnector(endpoint="udpin:0.0.0.0:14550")
        c.connect()

        # 39.9042 N, 116.4074 E, 100 m, heading 90 deg
        msg = _msg(
            "GLOBAL_POSITION_INT",
            sysid=7,
            lat=399042000,
            lon=1164074000,
            alt=100_000,        # mm
            relative_alt=100_000,
            vx=0, vy=0, vz=0,
            hdg=9000,           # centidegrees -> 90.0
        )
        slot = c.handle_message(msg)

    assert slot is not None
    assert 7 in c.telemetry
    assert abs(slot["lat"] - 39.9042) < 1e-6
    assert abs(slot["lng"] - 116.4074) < 1e-6
    assert abs(slot["alt"] - 100.0) < 1e-6
    assert abs(slot["heading"] - 90.0) < 1e-6

    for key in (
        "drone_id", "lat", "lng", "alt", "speed", "heading",
        "roll", "pitch", "yaw", "battery_pct", "gps_sats", "ts",
    ):
        assert key in slot


def test_multiple_message_aggregation() -> None:
    with patch(
        "app.services.mavlink_connector.mavutil.mavlink_connection",
        return_value=MagicMock(),
    ):
        from app.services.mavlink_connector import MavlinkConnector

        c = MavlinkConnector()
        c.connect()

        c.handle_message(_msg(
            "GLOBAL_POSITION_INT",
            sysid=1, lat=100_000_000, lon=200_000_000,
            alt=50_000, relative_alt=50_000, vx=0, vy=0, vz=0, hdg=0,
        ))
        c.handle_message(_msg(
            "ATTITUDE", sysid=1,
            roll=0.1, pitch=0.2, yaw=0.3,
            rollspeed=0, pitchspeed=0, yawspeed=0, time_boot_ms=0,
        ))
        c.handle_message(_msg(
            "SYS_STATUS", sysid=1,
            battery_remaining=85, voltage_battery=12_600,
        ))
        c.handle_message(_msg(
            "GPS_RAW_INT", sysid=1, satellites_visible=12,
        ))
        c.handle_message(_msg(
            "VFR_HUD", sysid=1,
            airspeed=5.0, groundspeed=4.5, heading=45,
            throttle=60, alt=50.0, climb=0.1,
        ))

    slot = c.telemetry[1]
    assert slot["roll"] == 0.1
    assert slot["pitch"] == 0.2
    assert slot["yaw"] == 0.3
    assert slot["battery_pct"] == 85
    assert abs(slot["voltage_battery"] - 12.6) < 1e-6
    assert slot["gps_sats"] == 12
    assert slot["speed"] == 4.5
    assert slot["throttle"] == 60


def test_unknown_message_returns_none() -> None:
    with patch(
        "app.services.mavlink_connector.mavutil.mavlink_connection",
        return_value=MagicMock(),
    ):
        from app.services.mavlink_connector import MavlinkConnector

        c = MavlinkConnector()
        c.connect()
        assert c.handle_message(_msg("STATUSTEXT", sysid=1, text="hi")) is None


def test_stream_payload_is_str_only() -> None:
    with patch(
        "app.services.mavlink_connector.mavutil.mavlink_connection",
        return_value=MagicMock(),
    ):
        from app.services.mavlink_connector import MavlinkConnector

        c = MavlinkConnector()
        c.connect()
        c.handle_message(_msg(
            "GLOBAL_POSITION_INT",
            sysid=1, lat=100_000_000, lon=200_000_000,
            alt=50_000, relative_alt=50_000, vx=0, vy=0, vz=0, hdg=0,
        ))
        payload = c._stream_payload(c.telemetry[1])

    assert all(isinstance(v, str) for v in payload.values())
    assert set(payload.keys()) == {
        "ts", "lat", "lng", "alt", "speed", "heading",
        "roll", "pitch", "yaw", "battery_pct", "gps_sats",
    }
