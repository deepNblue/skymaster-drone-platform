"""Tests for the DJI Cloud API connector skeleton (mock mode)."""
from __future__ import annotations

import uuid

import pytest

from app.services.dji_cloud_connector import (
    DJICloudConnector,
    METHOD_LIVE_START,
    METHOD_RTL,
    METHOD_TASK_CANCEL,
    METHOD_TASK_EXECUTE,
    METHOD_TASK_PAUSE,
    METHOD_TASK_PREPARE,
    TOPIC_OSD,
    TOPIC_SERVICES,
    TOPIC_STATUS,
    envelope,
)


def _mock(**kw) -> DJICloudConnector:
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="mock", **kw)
    c.connect()
    return c


# --- envelope ---------------------------------------------------------------
def test_envelope_shape():
    msg = envelope("flighttask_prepare", {"a": 1})
    uuid.UUID(msg["bid"])
    uuid.UUID(msg["tid"])
    assert msg["method"] == "flighttask_prepare"
    assert msg["data"] == {"a": 1}
    assert msg["need_reply"] == 1
    assert isinstance(msg["timestamp"], int) and msg["timestamp"] > 1_000_000_000_000


def test_envelope_unique_ids():
    a, b = envelope("m", {}), envelope("m", {})
    assert a["bid"] != b["bid"] and a["tid"] != b["tid"]


# --- topics -----------------------------------------------------------------
def test_topic_rules():
    c = DJICloudConnector(gateway_sn="DOCK123", mode="mock")
    assert c.topic(TOPIC_STATUS) == "sys/product/DOCK123/status"
    assert c.topic(TOPIC_OSD) == "thing/product/DOCK123/osd"
    assert c.topic(TOPIC_SERVICES) == "thing/product/DOCK123/services"


def test_subscribe_topics_cover_telemetry_and_commands():
    subs = _mock().subscribe_topics()
    assert "sys/product/TESTDOCK/status" in subs
    assert "thing/product/TESTDOCK/osd" in subs
    assert "thing/product/TESTDOCK/services_reply" in subs
    assert all(t.startswith(("sys/", "thing/")) for t in subs)


# --- topology / telemetry ---------------------------------------------------
def test_mock_connect_builds_topology():
    c = _mock(mock_drones=3)
    assert c.topology["gateway"]["sn"] == "TESTDOCK"
    assert [d["sn"] for d in c.topology["sub_devices"]] == [
        "MOCKM300-01", "MOCKM300-02", "MOCKM300-03",
    ]


def test_mock_osd_maps_to_canonical_telemetry():
    c = _mock()
    frames = c.mock_tick(0.5)
    assert len(frames) == 1
    osd = frames[0]
    assert 22.8 < osd["latitude"] < 22.9  # Nanning
    assert 108.3 < osd["longitude"] < 108.4
    slot = c.telemetry["MOCKM300-01"]
    assert slot["lat"] == osd["latitude"]
    assert slot["lng"] == osd["longitude"]
    assert slot["alt"] == osd["height"]
    assert slot["battery_pct"] == 87.0
    assert slot["source"] == "dji_cloud"
    assert slot["drone_id"] == "MOCKM300-01"


def test_parse_osd_accepts_snake_and_short_keys():
    c = _mock()
    slot = c.parse_osd({
        "sn": "ABC", "lat": 22.81, "lng": 108.31, "altitude": 150.0,
        "speed": 5.0, "battery_percent": 60, "gps_sats": 12,
    })
    assert slot["lat"] == 22.81 and slot["lng"] == 108.31
    assert slot["alt"] == 150.0
    assert slot["battery_pct"] == 60.0
    assert slot["gps_sats"] == 12.0


def test_drone_id_map_applied():
    uid = str(uuid.uuid4())
    c = _mock(drone_id_map={"MOCKM300-01": uid})
    c.mock_tick()
    assert c.telemetry["MOCKM300-01"]["drone_id"] == uid


# --- commands ---------------------------------------------------------------
def test_service_calls_are_recorded():
    seen = []
    c = _mock(on_message=lambda topic, msg: seen.append((topic, msg["method"])))
    assert c.flighttask_prepare("MOCKM300-01", [{"lat": 22.82, "lng": 108.32}])
    assert c.flighttask_execute("t-1", "f-1")
    assert c.return_home("MOCKM300-01")
    assert c.start_live("MOCKM300-01", "rtmp://127.0.0.1:1935/live")
    methods = [m for _, m in seen]
    assert methods == [METHOD_TASK_PREPARE, METHOD_TASK_EXECUTE, METHOD_RTL,
                       METHOD_LIVE_START]
    assert all(t == "thing/product/TESTDOCK/services" for t, _ in seen)


def test_flighttask_prepare_carries_waypoints():
    c = _mock()
    c.flighttask_prepare("MOCKM300-01", [
        {"lat": 22.81, "lng": 108.31, "alt": 80},
        {"lat": 22.82, "lng": 108.32, "alt": 90},
    ], flight_id="fp-1")
    mission = c._mock_mission["MOCKM300-01"]
    assert mission["waypoints"][1]["alt"] == 90.0


def test_mock_mission_state_machine():
    c = _mock()
    sn = "MOCKM300-01"
    c.flighttask_prepare(sn, [{"lat": 22.82, "lng": 108.32}])
    assert c._mock_state[sn] == "READY"
    c.flighttask_execute("t-1", "f-1")
    assert c._mock_state[sn] == "FLYING"
    c.flighttask_pause("t-1")
    assert c._mock_state[sn] == "PAUSED"
    c.flighttask_resume("t-1")
    assert c._mock_state[sn] == "FLYING"
    c.flighttask_cancel("t-1")
    assert c._mock_state[sn] == "HOVER"
    assert sn not in c._mock_mission


def test_mock_tick_advances_mission_progress():
    c = _mock()
    sn = "MOCKM300-01"
    c.flighttask_prepare(sn, [
        {"lat": 22.81, "lng": 108.31},
        {"lat": 22.82, "lng": 108.32},
        {"lat": 22.83, "lng": 108.33},
    ])
    c.flighttask_execute("t-1", "f-1")
    c.mock_tick(1.0)
    c.mock_tick(1.0)
    assert c._mock_mission[sn]["idx"] == 2


# --- mode validation --------------------------------------------------------
def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        DJICloudConnector(mode="bogus")


def test_cloud_mode_requires_paho(monkeypatch):
    from app.services import dji_cloud_connector as mod
    monkeypatch.setattr(mod, "mqtt", None)
    with pytest.raises(RuntimeError, match="paho-mqtt"):
        DJICloudConnector(mode="cloud")


# --- redis publish ----------------------------------------------------------
@pytest.mark.asyncio
async def test_publish_once_writes_redis_stream():
    class FakeRedis:
        def __init__(self):
            self.writes = []

        async def xadd(self, stream, payload):
            self.writes.append((stream, payload))

    r = FakeRedis()
    c = DJICloudConnector(mode="mock", redis_client=r,
                          drone_id_map={"MOCKM300-01": "drone-uuid"})
    c.connect()
    c.mock_tick()
    await c.publish_once()
    assert len(r.writes) == 1
    stream, payload = r.writes[0]
    assert stream == "telemetry:drone-uuid"
    assert float(payload["lat"]) > 0
    assert payload["source"] == "dji_cloud"
