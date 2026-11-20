"""DJI Cloud API connector — SkyMaster cloud-side adapter (skeleton).

This module implements the *cloud platform side* of DJI Cloud API v2: it
subscribes to device telemetry/topology and dispatches services commands to
the Dock / Pilot gateway over MQTT. It mirrors :class:`MavlinkConnector`'s
shape so it can be dropped into the telemetry stack later.

Two modes
---------
``mode="cloud"``
    Real devices. Requires ``paho-mqtt`` (soft dependency) and credentials
    obtained from the DJI developer portal (app_id / app_key / app_license).
    The cloud platform is the MQTT client that connects to the DJI broker;
    Dock / Pilot 2 also connect there with their own credentials.

``mode="mock"`` (default)
    No paho, no broker, no credentials. Generates DJI-shaped OSD / state /
    topology messages for a fake Dock + M300 flying over Nanning, and answers
    services calls. Lets us develop and test the full ingest + command path
    before hardware arrives.

Protocol notes (DJI Cloud API v2 / Edge SDK V2):
    * Topic families: ``sys/product/{sn}/status`` (topology),
      ``thing/product/{sn}/osd`` (telemetry, QoS0),
      ``thing/product/{sn}/state|events|services_reply`` (QoS1),
      ``thing/product/{sn}/services`` (cloud -> device commands).
    * Envelope: ``bid`` (business uuid), ``tid`` (technical uuid),
      ``timestamp`` (ms), ``method``, ``data``, ``gateway`` (on reply),
      ``need_reply`` (0/1).
    * Waypoint missions use WPML (KMZ); here we carry a waypoint list in
      ``data`` as a skeleton — swap in a real WPML file when a Dock is present.
    * OSD fields are DJI-specific (``latitude``/``longitude``/``altitude``/
      ``height``/``gimbal`` etc.); :meth:`parse_osd` maps them to SkyMaster's
      canonical telemetry slot used by MAVLink.

All credentials / endpoints are read from :class:`app.config.Settings` or
constructor kwargs — never hard-coded.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

try:  # soft dep — mock mode needs nothing
    import paho.mqtt.client as mqtt  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    mqtt = None  # type: ignore[assignment]

logger = logging.getLogger("skymaster.dji")


# --- protocol constants -----------------------------------------------------
TOPIC_STATUS = "sys/product/{sn}/status"
TOPIC_STATUS_REPLY = "sys/product/{sn}/status_reply"
TOPIC_OSD = "thing/product/{sn}/osd"
TOPIC_STATE = "thing/product/{sn}/state"
TOPIC_EVENTS = "thing/product/{sn}/events"
TOPIC_SERVICES = "thing/product/{sn}/services"
TOPIC_SERVICES_REPLY = "thing/product/{sn}/services_reply"
TOPIC_DRC = "thing/product/{sn}/drc"

METHOD_TOPO = "update_topo"
METHOD_DRC = "control"
METHOD_TASK_PREPARE = "flighttask_prepare"
METHOD_TASK_EXECUTE = "flighttask_execute"
METHOD_TASK_PAUSE = "flighttask_pause"
METHOD_TASK_RESUME = "flighttask_resume"
METHOD_TASK_CANCEL = "flighttask_cancel"
METHOD_TASK_PROGRESS = "flighttask_progress"
METHOD_LIVE_START = "live_start_push"
METHOD_LIVE_STOP = "live_stop_push"
METHOD_RTL = "return_home"

# Canonical telemetry keys shared with MavlinkConnector._slot().
_TELEMETRY_KEYS = (
    "ts", "drone_id", "lat", "lng", "alt", "height", "speed", "heading",
    "roll", "pitch", "yaw", "battery_pct", "gps_sats", "mode", "source",
)


def envelope(method: str, data: Dict[str, Any], need_reply: int = 1) -> Dict[str, Any]:
    """Build a DJI Cloud API v2 message envelope."""
    return {
        "bid": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "method": method,
        "data": data,
        "need_reply": need_reply,
    }


# --- DRC (real-time remote control) ----------------------------------------
# DJI Cloud API packs four stick channels into one signed 32-bit integer:
#   bits 0..12  throttle (thrust), 13..25 yaw, 26..38 pitch, 39..51 roll
# each channel is [-10000, 10000] mapped to a 13-bit offset (+10000).  The
# exact bit layout is workspace/firmware specific; keep the packing isolated
# here so it can be swapped without touching command routing.
DRC_CHANNEL_RANGE = 10000
DRC_CHANNEL_BITS = 16  # 0..20000 fits in 16 bits (must exceed 2*RANGE)


def pack_drc(*, throttle: float = 0.0, yaw: float = 0.0,
             pitch: float = 0.0, roll: float = 0.0) -> int:
    """Pack four normalized stick axes [-1, 1] into DJI's DRC integer."""
    def _chan(v: float) -> int:
        v = max(-1.0, min(1.0, float(v)))
        return int(round((v + 1.0) * DRC_CHANNEL_RANGE))  # 0..20000

    return (
        _chan(throttle)
        | (_chan(yaw) << (DRC_CHANNEL_BITS * 1))
        | (_chan(pitch) << (DRC_CHANNEL_BITS * 2))
        | (_chan(roll) << (DRC_CHANNEL_BITS * 3))
    )


def unpack_drc(value: int) -> Dict[str, float]:
    """Inverse of :func:`pack_drc` — useful for tests and mock replay."""
    mask = (1 << DRC_CHANNEL_BITS) - 1

    def _chan(shift: int) -> float:
        raw = (int(value) >> shift) & mask
        return round(raw / float(DRC_CHANNEL_RANGE) - 1.0, 4)

    return {
        "throttle": _chan(0),
        "yaw": _chan(DRC_CHANNEL_BITS * 1),
        "pitch": _chan(DRC_CHANNEL_BITS * 2),
        "roll": _chan(DRC_CHANNEL_BITS * 3),
    }


def reconnect_delay(attempt: int, base_s: float = 1.0,
                    cap_s: float = 60.0, jitter: float = 0.2) -> float:
    """Exponential backoff with jitter: base*2^n capped at ``cap_s``."""
    if attempt <= 0:
        return 0.0
    delay = min(cap_s, base_s * (2 ** (attempt - 1)))
    # Deterministic bounded jitter (no RNG dependency) keeps tests stable.
    jitter_amount = delay * jitter * (0.5 if attempt % 2 else -0.5)
    return max(0.0, delay + jitter_amount)


class DJICloudConnector:
    """Cloud-side connector for a DJI Dock / Pilot gateway.

    Parameters
    ----------
    gateway_sn:
        DJI gateway serial (Dock SN or RC SN). Topic ``{sn}`` substitute.
    mode:
        ``"mock"`` (default) or ``"cloud"``.
    broker_host / broker_port:
        MQTT broker (DJI Cloud API: 443 HTTPS / 1883 or 8883 MQTT). In real
        deployments this is the endpoint given by DJI for your workspace.
    client_id / username / password:
        MQTT login. For cloud side these come from DJI's workspace console.
    redis_client:
        Optional async Redis client; when set, parsed telemetry is published
        to ``telemetry:{drone_id}`` just like MavlinkConnector.
    drone_id_map:
        ``device_sn -> SkyMaster Drone UUID`` mapping for stream keys.
    on_message:
        Optional sync callback ``(topic, envelope_dict)`` for tests / routing.
    """

    def __init__(
        self,
        gateway_sn: str = "MOCKDOCK001",
        mode: str = "mock",
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        client_id: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        redis_client: Any = None,
        drone_id_map: Optional[Dict[str, str]] = None,
        on_message: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        mock_start_lat: float = 22.8167,
        mock_start_lng: float = 108.3167,
        mock_drones: int = 1,
    ) -> None:
        if mode not in ("mock", "cloud"):
            raise ValueError(f"invalid DJI connector mode: {mode!r}")
        if mode == "cloud" and mqtt is None:
            raise RuntimeError(
                "paho-mqtt is required for mode='cloud'; "
                "install with: pip install paho-mqtt"
            )
        self.gateway_sn = gateway_sn
        self.mode = mode
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id or gateway_sn
        self.username = username
        self.password = password
        self.redis = redis_client
        self.drone_id_map = dict(drone_id_map or {})
        self.on_message = on_message
        self.mock_start_lat = mock_start_lat
        self.mock_start_lng = mock_start_lng
        self.mock_drones = max(1, mock_drones)

        self.telemetry: Dict[str, Dict[str, Any]] = {}
        self.topology: Dict[str, Any] = {}
        self._client: Any = None
        self._connected = False
        self._stop = asyncio.Event()
        self._mock_t = 0.0
        # reconnect state (cloud mode)
        self._reconnect_attempt = 0
        self._reconnect_cap_s = 60.0
        self._reconnect_base_s = 1.0
        self.last_drc: Dict[str, Dict[str, float]] = {}

    # ---------------------------------------------------------------- topics
    def topic(self, template: str, sn: Optional[str] = None) -> str:
        return template.format(sn=sn or self.gateway_sn)

    def subscribe_topics(self) -> List[str]:
        """Topics the cloud platform subscribes to for one gateway."""
        return [
            self.topic(TOPIC_STATUS),
            self.topic(TOPIC_OSD),
            self.topic(TOPIC_STATE),
            self.topic(TOPIC_EVENTS),
            self.topic(TOPIC_SERVICES_REPLY),
        ]

    # ---------------------------------------------------------------- conn
    def connect(self) -> Any:
        """Connect to the DJI MQTT broker (cloud mode) or init mock state."""
        if self.mode == "mock":
            self.topology = {
                "gateway": {
                    "sn": self.gateway_sn, "domain": 3, "type": 3,
                    "sub_type": 0, "thing_version": "2.0",
                },
                "sub_devices": [
                    {
                        "sn": f"MOCKM300-{i + 1:02d}", "domain": 0, "type": 1,
                        "sub_type": 0, "index": i + 1,
                    }
                    for i in range(self.mock_drones)
                ],
            }
            self._connected = True
            logger.info(
                "DJI mock connector ready: gateway=%s drones=%d",
                self.gateway_sn, self.mock_drones,
            )
            return self

        client = mqtt.Client(client_id=self.client_id, clean_session=True)
        if self.username:
            client.username_pw_set(self.username, self.password or "")
        client.on_connect = self._on_mqtt_connect
        client.on_disconnect = self._on_mqtt_disconnect
        client.on_message = self._on_mqtt_message
        client.connect(self.broker_host, self.broker_port, keepalive=30)
        self._client = client
        return client

    def _on_mqtt_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc != 0:
            logger.error("DJI MQTT connect failed: CONNACK=%s", rc)
            return
        self._connected = True
        self._reconnect_attempt = 0  # reset backoff after a good connection
        if client is not None:  # guard for direct callback invocation in tests
            for t in self.subscribe_topics():
                client.subscribe(t, qos=1)
        logger.info("DJI MQTT connected, subscribed %d topics", len(self.subscribe_topics()))

    def _on_mqtt_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        """Mark disconnected; ``run`` drives reconnection with backoff."""
        self._connected = False
        if rc != 0:
            logger.warning("DJI MQTT unexpected disconnect (rc=%s)", rc)

    def reconnect_once(self) -> float:
        """Attempt a single reconnect; return the delay before the *next* try.

        Kept synchronous and side-effect-scoped so it is directly testable
        without a live broker. ``run`` awaits the returned delay.
        """
        self._reconnect_attempt += 1
        delay = reconnect_delay(
            self._reconnect_attempt, self._reconnect_base_s, self._reconnect_cap_s)
        if self._client is None:
            return delay
        try:
            self._client.reconnect()
            logger.info("DJI MQTT reconnect attempt %d scheduled", self._reconnect_attempt)
        except Exception:  # noqa: BLE001
            logger.warning("DJI MQTT reconnect attempt %d failed", self._reconnect_attempt)
        return delay

    def _on_mqtt_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("DJI bad JSON on %s", msg.topic)
            return
        if self.on_message:
            self.on_message(msg.topic, payload)
        method = payload.get("method", "")
        data = payload.get("data") or {}
        if method == METHOD_TOPO:
            self.topology = data
        elif msg.topic.endswith("/osd"):
            self.parse_osd(data)

    # ------------------------------------------------------------- commands
    def publish_service(self, method: str, data: Dict[str, Any]) -> bool:
        """Send a cloud -> device service call on ``thing/product/{sn}/services``."""
        topic = self.topic(TOPIC_SERVICES)
        msg = envelope(method, data)
        if self.mode == "mock":
            self._handle_mock_service(method, data)
            logger.info("[MOCK] DJI service %s -> %s", method, topic)
            if self.on_message:
                self.on_message(topic, msg)
            return True
        if not self._client or not self._connected:
            logger.warning("publish_service: MQTT not connected")
            return False
        info = self._client.publish(topic, json.dumps(msg), qos=1)
        return info.rc == mqtt.MQTT_ERR_SUCCESS  # type: ignore[union-attr]

    def flighttask_prepare(self, drone_sn: str, waypoints: List[Dict[str, Any]],
                           flight_id: Optional[str] = None) -> bool:
        """Prepare a waypoint mission. Real deployments attach a WPML KMZ file."""
        return self.publish_service(METHOD_TASK_PREPARE, {
            "flight_id": flight_id or str(uuid.uuid4()),
            "task_type": 0,
            "drone_sn": drone_sn,
            # Skeleton: real Cloud API expects a KMZ reference here (WPML).
            "waypoints": [
                {"lat": float(w["lat"]), "lng": float(w["lng"]),
                 "alt": float(w.get("alt", 50.0))}
                for w in waypoints
            ],
        })

    def flighttask_execute(self, task_id: str, flight_id: str) -> bool:
        return self.publish_service(
            METHOD_TASK_EXECUTE, {"task_id": task_id, "flight_id": flight_id})

    def flighttask_pause(self, task_id: str) -> bool:
        return self.publish_service(METHOD_TASK_PAUSE, {"task_id": task_id})

    def flighttask_resume(self, task_id: str) -> bool:
        return self.publish_service(METHOD_TASK_RESUME, {"task_id": task_id})

    def flighttask_cancel(self, task_id: str) -> bool:
        return self.publish_service(METHOD_TASK_CANCEL, {"task_id": task_id})

    def start_live(self, drone_sn: str, rtmp_url: str,
                   video_id: Optional[str] = None) -> bool:
        """Start pushing a camera stream to our MediaMTX RTMP ingest."""
        return self.publish_service(METHOD_LIVE_START, {
            "url_type": 1,  # RTMP
            "url": rtmp_url,
            "video_id": video_id or f"{drone_sn}/0/0",
            "video_quality": 3,  # HD
        })

    def return_home(self, drone_sn: str) -> bool:
        return self.publish_service(METHOD_RTL, {"drone_sn": drone_sn})

    def send_drc(self, drone_sn: str, *, throttle: float = 0.0,
                 yaw: float = 0.0, pitch: float = 0.0,
                 roll: float = 0.0) -> bool:
        """Send a real-time stick command on ``thing/product/{sn}/drc``.

        Axes are normalized [-1, 1]; ``need_reply=0`` because DRC is a
        high-frequency fire-and-forget control stream.
        """
        drc_value = pack_drc(throttle=throttle, yaw=yaw, pitch=pitch, roll=roll)
        topic = self.topic(TOPIC_DRC)  # gateway (Dock) topic; drone in data
        msg = envelope(METHOD_DRC, {
            "drone_sn": drone_sn,
            "drc": drc_value,
            "control_source": "skymaster",
        }, need_reply=0)
        if self.mode == "mock":
            self.last_drc[drone_sn] = unpack_drc(drc_value)
            self._mock_state[drone_sn] = "DRC"
            if self.on_message:
                self.on_message(topic, msg)
            return True
        if not self._client or not self._connected:
            logger.warning("send_drc: MQTT not connected")
            return False
        info = self._client.publish(topic, json.dumps(msg), qos=0)
        return info.rc == mqtt.MQTT_ERR_SUCCESS  # type: ignore[union-attr]

    # -------------------------------------------------------------- parsing
    def parse_osd(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Map a DJI OSD payload to SkyMaster's canonical telemetry slot."""
        sn = str(data.get("sn") or data.get("drone_sn") or self.gateway_sn)
        slot = self.telemetry.setdefault(sn, {k: None for k in _TELEMETRY_KEYS})
        slot["drone_id"] = self.drone_id_map.get(sn, sn)
        slot["source"] = "dji_cloud"
        # DJI OSD: latitude/longitude in degrees; altitude = ASL (m),
        # height = relative to home (m). Prefer relative height for `alt`
        # to match MAVLink GLOBAL_POSITION_INT.relative_alt semantics.
        slot["lat"] = _num(data.get("latitude", data.get("lat")))
        slot["lng"] = _num(data.get("longitude", data.get("lng")))
        slot["alt"] = _num(data.get("height", data.get("altitude")))
        slot["height"] = _num(data.get("height"))
        slot["speed"] = _num(data.get("speed", data.get("horizontal_speed")))
        slot["heading"] = _num(data.get("yaw", data.get("heading")))
        slot["battery_pct"] = _num(data.get("battery", data.get("battery_percent")))
        slot["gps_sats"] = _num(data.get("gps_satellite_num", data.get("gps_sats")))
        slot["mode"] = data.get("flight_status", data.get("mode"))
        slot["ts"] = time.time()
        return slot

    # ----------------------------------------------------------------- mock
    def _mock_osd(self, i: int) -> Dict[str, Any]:
        """Generate one DJI-shaped OSD frame for a fake M300 over Nanning."""
        sn = f"MOCKM300-{i + 1:02d}"
        # slow circle around start point (~200m radius)
        r = 0.002
        lat = self.mock_start_lat + r * math.cos(self._mock_t + i)
        lng = self.mock_start_lng + r * math.sin(self._mock_t + i)
        return {
            "sn": sn,
            "latitude": round(lat, 7),
            "longitude": round(lng, 7),
            "altitude": 120.0,
            "height": 100.0 + 2.0 * math.sin(self._mock_t + i),
            "horizontal_speed": 8.5,
            "yaw": round((self._mock_t * 30 + i * 90) % 360, 1),
            "battery": 87 - i,
            "gps_satellite_num": 18,
            "flight_status": self._mock_state.get(sn, "HOVER"),
        }

    _mock_state: Dict[str, str] = {}
    _mock_mission: Dict[str, Dict[str, Any]] = {}

    def _handle_mock_service(self, method: str, data: Dict[str, Any]) -> None:
        sn = data.get("drone_sn", "MOCKM300-01")
        if method == METHOD_TASK_PREPARE:
            self._mock_mission[sn] = {
                "waypoints": data.get("waypoints", []), "idx": 0,
            }
            self._mock_state[sn] = "READY"
        elif method == METHOD_TASK_EXECUTE:
            self._mock_state[sn] = "FLYING"
        elif method == METHOD_TASK_PAUSE:
            self._mock_state[sn] = "PAUSED"
        elif method == METHOD_TASK_RESUME:
            self._mock_state[sn] = "FLYING"
        elif method == METHOD_TASK_CANCEL:
            self._mock_state[sn] = "HOVER"
            self._mock_mission.pop(sn, None)
        elif method == METHOD_RTL:
            self._mock_state[sn] = "RETURN_TO_HOME"
        elif method == METHOD_LIVE_START:
            self._mock_state[sn] = "LIVE"

    def mock_tick(self, dt: float = 0.5) -> List[Dict[str, Any]]:
        """Advance mock simulation by ``dt`` seconds; return OSD payloads."""
        self._mock_t += dt
        frames = []
        for i in range(self.mock_drones):
            osd = self._mock_osd(i)
            frames.append(osd)
            self.parse_osd(osd)
            m = self._mock_mission.get(osd["sn"])
            if m and self._mock_state.get(osd["sn"]) == "FLYING":
                if m["idx"] < len(m["waypoints"]):
                    m["idx"] += 1
        return frames

    # ----------------------------------------------------------- run/publish
    async def run(self, tick_s: float = 0.5) -> None:
        """Publish loop for telemetry stack compatibility with MavlinkConnector.

        In cloud mode a dropped MQTT link is reconnected with exponential
        backoff (see :meth:`reconnect_once`); mock mode just advances the sim.
        """
        if self.mode == "cloud" and self._client is not None:
            self._client.loop_start()
        logger.info("DJI connector run loop started (mode=%s)", self.mode)
        try:
            while not self._stop.is_set():
                if self.mode == "mock":
                    self.mock_tick(tick_s)
                elif self.mode == "cloud" and not self._connected:
                    delay = self.reconnect_once()
                    await asyncio.sleep(delay)
                    continue
                await self.publish_once()
                await asyncio.sleep(tick_s)
        finally:
            if self.mode == "cloud" and self._client is not None:
                self._client.loop_stop()

    def stop(self) -> None:
        self._stop.set()

    def _stream_payload(self, slot: Dict[str, Any]) -> Dict[str, str]:
        fields = ("ts", "lat", "lng", "alt", "speed", "heading",
                  "battery_pct", "gps_sats", "mode", "source")
        return {k: ("" if slot.get(k) is None else str(slot[k])) for k in fields}

    async def publish_once(self) -> None:
        """Publish canonical telemetry to Redis streams (if configured)."""
        if self.redis is None:
            return
        for sn, slot in list(self.telemetry.items()):
            stream = f"telemetry:{self.drone_id_map.get(sn, sn)}"
            try:
                await self.redis.xadd(stream, self._stream_payload(slot))
            except Exception:  # noqa: BLE001
                logger.exception("DJI telemetry publish failed: %s", stream)


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
