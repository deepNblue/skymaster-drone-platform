"""Calibration state machine and RC persistence tests (config-driven)."""
from __future__ import annotations

import json

import pytest

from app.services.dji_cloud_connector import (
    DJICloudConnector, RC_AXES, RC_CALIBRATION_ITEM,
)

SN = "MOCKM300-01"


@pytest.fixture
def conn(tmp_path):
    cfg = tmp_path / "cal.json"
    cfg.write_text(json.dumps({
        "sensor_calibration": {
            "compass": {"label": "指南针", "duration_s": 4, "hint": "旋转360度"},
            "gimbal": {"label": "云台", "duration_s": 2, "hint": "保持静止"},
        },
        "rc_calibration": {
            "deadzone": 0.1,
            "steps": [{"key": "center", "axis": "all", "edge": "center", "label": "回中"}],
        },
    }), encoding="utf-8")
    c = DJICloudConnector(
        mode="mock", mock_drones=1,
        calibration_config_path=str(cfg),
        rc_calibration_path=str(tmp_path / "rc.json"),
    )
    c.connect()
    return c


def test_items_are_config_driven(conn):
    items = conn.calibration_items()
    assert [i["key"] for i in items] == ["compass", "gimbal", RC_CALIBRATION_ITEM]
    assert items[0]["duration_s"] == 4
    assert items[-1]["kind"] == "rc"


def test_mock_sensor_calibration_progresses_to_success(conn):
    assert conn.start_calibration(SN, "compass") is True
    st = conn.calibration_status(SN)["sensors"][SN]["compass"]
    assert st["state"] == "running"
    assert st["progress"] == 0

    conn.mock_tick(2.0)
    st = conn.calibration_status(SN)["sensors"][SN]["compass"]
    assert st["progress"] == 50.0

    conn.mock_tick(2.0)
    st = conn.calibration_status(SN)["sensors"][SN]["compass"]
    assert st["state"] == "success"
    assert st["progress"] == 100.0


def test_cancel_stops_calibration(conn):
    conn.start_calibration(SN, "gimbal")
    assert conn.cancel_calibration(SN, "gimbal") is True
    conn.mock_tick(10.0)
    st = conn.calibration_status(SN)["sensors"][SN]["gimbal"]
    assert st["state"] == "cancelled"
    assert st["progress"] == 0
    assert conn.cancel_calibration(SN, "gimbal") is True  # idempotent state update


def test_unknown_item_is_rejected(conn):
    assert conn.start_calibration(SN, "teleport") is False
    assert SN not in conn.calibration_status(SN)["sensors"] or \
        "teleport" not in conn.calibration_status(SN)["sensors"][SN]


def test_rc_persistence_and_axis_mapping(conn, tmp_path):
    axes = {
        "throttle": {"min": -0.9, "center": 0.02, "max": 0.95},
        "yaw": {"min": -0.8, "center": -0.01, "max": 0.85},
        "pitch": {"min": -0.7, "center": 0.0, "max": 0.75},
        "roll": {"min": -0.6, "center": 0.0, "max": 0.65},
    }
    assert conn.set_rc_calibration(SN, axes) is True
    saved_path = tmp_path / "rc.json"
    assert saved_path.exists()
    on_disk = json.loads(saved_path.read_text(encoding="utf-8"))
    assert on_disk[SN]["deadzone"] == 0.1  # from config, not hardcoded

    st = conn.calibration_status(SN)
    assert st["sensors"][SN][RC_CALIBRATION_ITEM]["state"] == "success"
    assert st["rc"][SN]["axes"]["throttle"]["max"] == 0.95

    # deadzone: small sticks around center map to zero
    assert conn.apply_rc_axis(SN, "throttle", 0.05) == 0.0
    # positive and negative halves scale against their own endpoint
    assert conn.apply_rc_axis(SN, "throttle", 0.95) == 1.0
    assert conn.apply_rc_axis(SN, "yaw", -0.8) == -1.0
    assert conn.apply_rc_axis(SN, "yaw", 0.42) == pytest.approx(0.5, abs=0.02)


def test_apply_rc_without_calibration_clamps(conn):
    assert conn.apply_rc_axis(SN, "roll", 1.5) == 1.0
    assert conn.apply_rc_axis(SN, "roll", -1.5) == -1.0


def test_cloud_style_progress_update(conn):
    conn.update_calibration(SN, "compass", state="running", progress=42, message="rotate")
    st = conn.calibration_status(SN)["sensors"][SN]["compass"]
    assert st["state"] == "running" and st["progress"] == 42
    assert st["message"] == "rotate"


def test_missing_axis_in_payload_is_rejected(conn):
    axes = {a: {"min": -1, "center": 0, "max": 1} for a in RC_AXES[:-1]}
    assert conn.set_rc_calibration(SN, axes) is False
