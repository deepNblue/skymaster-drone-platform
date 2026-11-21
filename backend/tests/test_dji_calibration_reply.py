"""services_reply -> calibration state machine routing tests."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.dji_cloud_connector import (
    DJICloudConnector, METHOD_CALIBRATION,
)

SN = "MOCKM300-01"
REPLY_TOPIC = "thing/product/TESTDOCK/services_reply"


@pytest.fixture
def conn():
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="mock", mock_drones=1)
    c.connect()
    return c


def feed(conn, payload, topic=REPLY_TOPIC):
    msg = SimpleNamespace(topic=topic, payload=json.dumps(payload).encode("utf-8"))
    conn._on_mqtt_message(None, None, msg)


def slot(conn, item="compass"):
    return conn.calibration_status(SN)["sensors"][SN][item]


def test_reply_drives_running_then_success(conn):
    conn.start_calibration(SN, "compass")
    feed(conn, {"method": "calibration", "data": {
        "drone_sn": SN, "item": "compass", "status": "running",
        "progress": 45, "message": "rotating",
    }})
    st = slot(conn)
    assert st["state"] == "running"
    assert st["progress"] == 45
    assert st["message"] == "rotating"

    feed(conn, {"method": "calibration", "data": {
        "drone_sn": SN, "item": "compass", "status": "done", "progress": 100,
    }})
    st = slot(conn)
    assert st["state"] == "success"
    assert st["progress"] == 100


def test_fractional_progress_and_numeric_status(conn):
    conn.start_calibration(SN, "imu")
    feed(conn, {"method": "calibration", "data": {
        "drone_sn": SN, "item": "imu", "status": 1, "progress": 0.5,
    }})
    st = slot(conn, "imu")
    assert st["state"] == "running"
    assert st["progress"] == 50.0


def test_nonzero_result_marks_failed(conn):
    conn.start_calibration(SN, "gimbal")
    feed(conn, {"method": "calibration", "data": {
        "drone_sn": SN, "item": "gimbal", "result": -1,
        "reason": "motor timeout", "progress": 30,
    }})
    st = slot(conn, "gimbal")
    assert st["state"] == "failed"
    assert st["message"] == "motor timeout"


def test_cancelled_reply(conn):
    conn.start_calibration(SN, "vision")
    feed(conn, {"method": "calibration", "data": {
        "drone_sn": SN, "item": "vision", "state": "cancelled", "progress": 10,
    }})
    assert slot(conn, "vision")["state"] == "cancelled"


def test_bid_correlation_recovers_item_and_sn(monkeypatch):
    # cloud mode without a live broker: start_calibration records pending
    # correlation ids before publish_service returns False. Stub the soft
    # paho-mqtt dependency so the test does not require a broker or the lib.
    monkeypatch.setattr(
        "app.services.dji_cloud_connector.mqtt",
        SimpleNamespace(MQTT_ERR_SUCCESS=0),
        raising=False,
    )
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="cloud")
    assert c.start_calibration(SN, "vision") is False
    assert len(c._pending_calibration) == 2
    bid = next(iter(c._pending_calibration))

    # Reply omits both item and drone_sn — correlation must recover them.
    feed(c, {"bid": bid, "data": {"status": "running", "progress": 20}})
    st = c.calibration_status(SN)["sensors"][SN]["vision"]
    assert st["state"] == "running"
    assert st["progress"] == 20
    assert c._pending_calibration == {}  # both bid and tid consumed


def test_non_calibration_reply_is_ignored(conn):
    conn.start_calibration(SN, "compass")
    feed(conn, {"method": "flighttask_progress", "data": {
        "drone_sn": SN, "item": "compass", "progress": 99,
    }})
    assert slot(conn)["progress"] == 0


def test_malformed_reply_does_not_crash(conn):
    conn.start_calibration(SN, "compass")
    msg = SimpleNamespace(topic=REPLY_TOPIC, payload=b"not-json")
    conn._on_mqtt_message(None, None, msg)  # logs warning, returns
    feed(conn, {"method": "calibration", "data": "not-a-dict"})
    assert slot(conn)["state"] == "running"


def test_on_message_callback_still_fires(conn):
    seen = []
    conn.on_message = lambda topic, payload: seen.append(topic)
    feed(conn, {"method": "calibration", "data": {
        "drone_sn": SN, "item": "compass", "status": "success", "progress": 100,
    }})
    assert seen == [REPLY_TOPIC]
    assert slot(conn)["state"] == "success"


def test_method_constant_is_calibration():
    assert METHOD_CALIBRATION == "calibration"
