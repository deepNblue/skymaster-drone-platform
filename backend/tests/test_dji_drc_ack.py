"""DRC command/ack telemetry loop tests (config-driven)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services.dji_cloud_connector import DJICloudConnector

SN = "MOCKM300-01"


def write_cfg(tmp_path, **overrides):
    cfg = {
        "drc": {
            "ack_delay_ms": 0,
            "ack_timeout_ms": 3000,
            "seq_wrap": 10,
            "ack_fields": ["drc_ack_seq", "drc_seq"],
        }
    }
    cfg["drc"].update(overrides)
    path = tmp_path / "control.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


@pytest.fixture
def conn(tmp_path):
    c = DJICloudConnector(
        mode="mock", mock_drones=1,
        control_config_path=write_cfg(tmp_path),
    )
    c.connect()
    return c


def feed_osd(conn, payload):
    msg = SimpleNamespace(
        topic="thing/product/TESTDOCK/osd",
        payload=json.dumps(payload).encode("utf-8"),
    )
    conn._on_mqtt_message(None, None, msg)


def test_send_records_pending_and_sequence(conn):
    assert conn.send_drc(SN, throttle=0.5, yaw=-0.2, pitch=0.1, roll=0.0)
    link = conn.drc_link_status()
    assert link["seq"] == 1
    assert link["ack_timeout_ms"] == 3000
    pending = link["pending"][SN]
    assert pending["seq"] == 1
    assert pending["axes"] == {
        "throttle": 0.5, "yaw": -0.2, "pitch": 0.1, "roll": 0.0,
    }
    assert pending["timed_out"] is False


def test_mock_tick_produces_ack(conn):
    conn.send_drc(SN, throttle=0.8)
    conn.mock_tick(0.01)  # ack_delay_ms=0 in fixture config
    link = conn.drc_link_status()
    ack = link["last_ack"][SN]
    assert ack["state"] == "acked"
    assert ack["seq"] == 1
    assert ack["axes"]["throttle"] == 0.8
    assert ack["latency_ms"] is not None and ack["latency_ms"] >= 0
    assert link["pending"] == {}


def test_no_ack_before_configured_delay(tmp_path):
    c = DJICloudConnector(
        mode="mock", mock_drones=1,
        control_config_path=write_cfg(tmp_path, ack_delay_ms=60000),
    )
    c.connect()
    c.send_drc(SN)
    c.mock_tick(0.5)
    assert SN in c.drc_link_status()["pending"]
    assert c.last_drc_ack == {}


def test_cloud_osd_carries_ack(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.dji_cloud_connector.mqtt",
        SimpleNamespace(MQTT_ERR_SUCCESS=0),
        raising=False,
    )
    c = DJICloudConnector(
        mode="cloud", gateway_sn="TESTDOCK",
        control_config_path=write_cfg(tmp_path),
    )
    c._client = SimpleNamespace(
        publish=lambda topic, payload, qos: SimpleNamespace(rc=0))
    c._connected = True
    assert c.send_drc(SN, throttle=0.3)

    feed_osd(c, {"sn": SN, "drc_ack_seq": c._drc_seq, "flight_status": "HOVER"})
    ack = c.drc_link_status()["last_ack"][SN]
    assert ack["state"] == "acked"
    assert ack["axes"]["throttle"] == 0.3
    assert c.drc_link_status()["pending"] == {}


def test_stale_sequence_is_ignored(conn):
    conn.send_drc(SN)
    assert conn.handle_drc_ack({"sn": SN, "drc_ack_seq": 999}) is False
    assert SN in conn.drc_link_status()["pending"]


def test_ack_without_sn_resolves_by_sequence(conn):
    conn.send_drc(SN, pitch=0.6)
    assert conn.handle_drc_ack({"drc_ack_seq": 1}) is True
    assert conn.last_drc_ack[SN]["axes"]["pitch"] == 0.6


def test_timeout_marks_last_ack(conn):
    conn.send_drc(SN)
    conn._drc_pending[SN]["sent_at"] -= 10.0  # avoid real sleep
    conn._expire_drc_pending()
    ack = conn.drc_link_status()["last_ack"][SN]
    assert ack["state"] == "timeout"
    assert ack["latency_ms"] is None
    assert conn.drc_link_status()["pending"] == {}


def test_custom_ack_field(tmp_path):
    c = DJICloudConnector(
        mode="mock", mock_drones=1,
        control_config_path=write_cfg(tmp_path, ack_fields=["vendor_ack"]),
    )
    c.connect()
    c.send_drc(SN)
    assert c.handle_drc_ack({"sn": SN, "vendor_ack": 1}) is True


def test_sequence_wraps(tmp_path):
    c = DJICloudConnector(
        mode="mock", mock_drones=1,
        control_config_path=write_cfg(tmp_path, seq_wrap=3),
    )
    c.connect()
    seqs = []
    for _ in range(4):
        c.send_drc(SN)
        seqs.append(c._drc_seq)
    assert seqs == [1, 2, 0, 1]


def test_status_api_exposes_drc_link(monkeypatch):
    monkeypatch.setenv("AUTH_OPTIONAL", "true")
    from app.config import settings
    monkeypatch.setattr(settings, "auth_optional", True)
    from app.main import app

    c = DJICloudConnector(mode="mock", mock_drones=1)
    c.connect()
    c.send_drc(SN, throttle=0.4)
    old = getattr(app.state, "dji_connector", None)
    app.state.dji_connector = c
    try:
        d = TestClient(app).get("/api/v1/dji/status").json()
        assert "drc_link" in d
        assert d["drc_link"]["pending"][SN]["axes"]["throttle"] == 0.4
    finally:
        if old is None:
            del app.state.dji_connector
        else:
            app.state.dji_connector = old
