"""Tests for the DJI Cloud API connector skeleton (mock mode)."""
from __future__ import annotations

import uuid

import pytest

from app.services.dji_cloud_connector import (
    DJICloudConnector,
    METHOD_DRC,
    METHOD_LIVE_START,
    METHOD_RTL,
    METHOD_TASK_CANCEL,
    METHOD_TASK_EXECUTE,
    METHOD_TASK_PAUSE,
    METHOD_TASK_PREPARE,
    TOPIC_DRC,
    TOPIC_OSD,
    TOPIC_SERVICES,
    TOPIC_STATUS,
    envelope,
    pack_drc,
    reconnect_delay,
    unpack_drc,
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


# --- DRC (real-time control) ------------------------------------------------
def test_drc_pack_unpack_roundtrip():
    axes = {"throttle": 0.5, "yaw": -0.25, "pitch": 1.0, "roll": -1.0}
    value = pack_drc(**axes)
    assert isinstance(value, int) and value >= 0
    decoded = unpack_drc(value)
    for k, v in axes.items():
        assert abs(decoded[k] - v) <= 0.001


def test_drc_pack_clamps_to_range():
    value = pack_drc(throttle=5.0, yaw=-9.0)
    decoded = unpack_drc(value)
    assert decoded["throttle"] == 1.0
    assert decoded["yaw"] == -1.0
    assert decoded["pitch"] == 0.0  # neutral stick


def test_send_drc_mock_records_state_and_message():
    seen = []
    c = _mock(on_message=lambda topic, msg: seen.append((topic, msg)))
    assert c.send_drc("MOCKM300-01", throttle=0.5, yaw=0.1)
    topic, msg = seen[-1]
    assert topic == "thing/product/TESTDOCK/drc"  # gateway topic
    assert msg["method"] == METHOD_DRC
    assert msg["need_reply"] == 0
    assert c.last_drc["MOCKM300-01"]["throttle"] == 0.5
    assert c._mock_state["MOCKM300-01"] == "DRC"


def test_drc_topic_template():
    # DRC is sent on the gateway topic; the template also allows explicit sn.
    c = _mock()
    assert c.topic(TOPIC_DRC) == "thing/product/TESTDOCK/drc"
    assert c.topic(TOPIC_DRC, sn="DOCK-B") == "thing/product/DOCK-B/drc"


# --- reconnect backoff ------------------------------------------------------
def test_reconnect_delay_grows_and_caps():
    assert reconnect_delay(0) == 0.0
    d1 = reconnect_delay(1, base_s=1.0, cap_s=60.0, jitter=0)
    d2 = reconnect_delay(2, base_s=1.0, cap_s=60.0, jitter=0)
    d3 = reconnect_delay(3, base_s=1.0, cap_s=60.0, jitter=0)
    assert d1 == 1.0 and d2 == 2.0 and d3 == 4.0
    assert reconnect_delay(100, base_s=1.0, cap_s=60.0, jitter=0) == 60.0


def test_reconnect_delay_jitter_is_bounded():
    for attempt in range(1, 8):
        d = reconnect_delay(attempt, base_s=1.0, cap_s=60.0, jitter=0.2)
        nominal = min(60.0, 1.0 * 2 ** (attempt - 1))
        assert 0.8 * nominal <= d <= 1.1 * nominal


def test_reconnect_once_increments_attempt_and_returns_delay():
    c = _mock()  # mock client is None; should still bump attempt + return delay
    delay = c.reconnect_once()
    assert c._reconnect_attempt == 1
    assert delay > 0


def test_on_mqtt_connect_resets_backoff():
    c = _mock()
    c._reconnect_attempt = 7
    c._on_mqtt_connect(None, None, None, 0)
    assert c._reconnect_attempt == 0
    assert c._connected is True


def test_on_mqtt_disconnect_marks_state():
    c = _mock()
    c._connected = True
    c._on_mqtt_disconnect(None, None, 7)
    assert c._connected is False
