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
    * Waypoint missions use WPML (KMZ). We generate a config-driven WPML
      wayline and package it as KMZ; the raw waypoint list stays in ``data``
      as a compatibility skeleton for mock/tests.
    * OSD fields are DJI-specific (``latitude``/``longitude``/``altitude``/
      ``height``/``gimbal`` etc.); :meth:`parse_osd` maps them to SkyMaster's
      canonical telemetry slot used by MAVLink.

All credentials / endpoints are read from :class:`app.config.Settings` or
constructor kwargs — never hard-coded.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import math
import os
import ssl
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

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
METHOD_CALIBRATION = "calibration"

RC_AXES = ("throttle", "yaw", "pitch", "roll")
RC_CALIBRATION_ITEM = "rc"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CALIBRATION_CONFIG = _BACKEND_ROOT / "config" / "dji_calibration.json"
DEFAULT_RC_CALIBRATION_FILE = _BACKEND_ROOT / "data" / "dji_rc_calibration.json"
DEFAULT_CONTROL_CONFIG = _BACKEND_ROOT / "config" / "dji_control.json"
DEFAULT_MISSION_CONFIG = _BACKEND_ROOT / "config" / "dji_mission.json"
DEFAULT_MISSION_ROUTES = _BACKEND_ROOT / "config" / "dji_mission_routes.json"
DEFAULT_TLS_CONFIG = _BACKEND_ROOT / "config" / "dji_mqtt_tls.json"
DEFAULT_WPML_CONFIG = _BACKEND_ROOT / "config" / "dji_wpml.json"

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
        calibration_config_path: Optional[str] = None,
        rc_calibration_path: Optional[str] = None,
        control_config_path: Optional[str] = None,
        mission_config_path: Optional[str] = None,
        mission_routes_path: Optional[str] = None,
        tls_config_path: Optional[str] = None,
        wpml_config_path: Optional[str] = None,
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
        # cloud mode: correlate services_reply -> (drone_sn, calibration item)
        self._pending_calibration: Dict[str, Tuple[str, str]] = {}

        # --- calibration (config-driven, no hardcoded durations/deadzone) ---
        self.calibration_config: Dict[str, Any] = self._load_calibration_config(
            calibration_config_path)
        self.rc_calibration_path = Path(
            rc_calibration_path or DEFAULT_RC_CALIBRATION_FILE)
        self._calibration: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._rc_calibration: Dict[str, Dict[str, Any]] = self._load_rc_calibration()

        # --- DRC command/ack loop (config-driven) -------------------------
        self.control_config: Dict[str, Any] = self._load_control_config(
            control_config_path)
        self._drc_seq = 0
        self._drc_pending: Dict[str, Dict[str, Any]] = {}
        self.last_drc_ack: Dict[str, Dict[str, Any]] = {}
        self._mock_state: Dict[str, str] = {}
        self._mock_mission: Dict[str, Dict[str, Any]] = {}

        # --- flight task state machine (config-driven) --------------------
        self.mission_config: Dict[str, Any] = self._load_json_config(
            mission_config_path, DEFAULT_MISSION_CONFIG, "mission config")
        self._mission_routes: List[Dict[str, Any]] = self._load_mission_routes(
            mission_routes_path)
        self._missions: Dict[str, Dict[str, Any]] = {}
        self._mission_by_sn: Dict[str, str] = {}

        # --- MQTT TLS / clientAuth (config-driven, credentials from env) ---
        self.tls_config: Dict[str, Any] = self._load_json_config(
            tls_config_path, DEFAULT_TLS_CONFIG, "mqtt tls config")
        self._tls_active = False

        # --- WPML / KMZ wayline generation (config-driven) ----------------
        self.wpml_config: Dict[str, Any] = self._load_json_config(
            wpml_config_path, DEFAULT_WPML_CONFIG, "wpml config")

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

    # ------------------------------------------------------------------ tls
    def _tls_cfg(self) -> Dict[str, Any]:
        return self.tls_config.get("tls") or {}

    @staticmethod
    def _resolve_tls_version(name: str) -> Any:
        """Resolve a config name to an ssl version accepted by paho.

        ``ssl.TLSVersion.TLSv1_2`` and ``ssl.PROTOCOL_TLSv1_2`` use mixed
        case, so match case-insensitively instead of uppercasing the key.
        """
        key = str(name).strip().replace("-", "_").lower()
        if not key:
            return None
        enum = getattr(ssl, "TLSVersion", None)
        if enum is not None:
            for member in dir(enum):
                if member.lower() == key:
                    return getattr(enum, member)
        for attr in dir(ssl):
            if attr.lower() == "protocol_" + key:
                return getattr(ssl, attr)
        return None

    def tls_status(self) -> Dict[str, Any]:
        """Non-sensitive TLS status for the status endpoint / UI."""
        cfg = self._tls_cfg()
        raw_ports = cfg.get("ports")
        ports = raw_ports if isinstance(raw_ports, list) else []
        auth = str(cfg.get("client_auth") or "none").lower()
        certfile = str(cfg.get("certfile") or "")
        keyfile = str(cfg.get("keyfile") or "")
        ca = str(cfg.get("ca_certs") or "")
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "active": self._tls_active,
            "port": self.broker_port,
            "ports": ports,
            "ca_configured": bool(ca),
            "client_cert_configured": bool(certfile and keyfile),
            "client_auth": auth,
            "tls_version": str(cfg.get("tls_version") or ""),
            "insecure_skip_verify": bool(cfg.get("insecure_skip_verify", False)),
        }

    def _configure_tls(self, client: Any) -> bool:
        """Apply CA / mutual-auth settings before the MQTT TCP connect.

        TLS is only applied on configured TLS ports (default 8883/443), so a
        local plaintext broker on 1883 keeps working unchanged.
        """
        cfg = self._tls_cfg()
        if not bool(cfg.get("enabled", True)):
            return False
        ports = cfg.get("ports")
        if not isinstance(ports, list) or not ports:
            ports = [8883]
        if self.broker_port not in ports:
            return False
        if not hasattr(client, "tls_set"):
            logger.warning("MQTT client has no tls_set(); TLS not applied")
            return False

        kwargs: Dict[str, Any] = {}
        ca = str(cfg.get("ca_certs") or "")
        if ca:
            kwargs["ca_certs"] = ca

        auth = str(cfg.get("client_auth") or "none").lower()
        if auth in ("optional", "required", "mutual"):
            cert = str(cfg.get("certfile") or "")
            key = str(cfg.get("keyfile") or "")
            if cert and key:
                kwargs["certfile"] = cert
                kwargs["keyfile"] = key
            else:
                logger.warning(
                    "client_auth=%s but certfile/keyfile missing; "
                    "mutual TLS disabled", auth)

        version_name = str(cfg.get("tls_version") or "")
        if version_name:
            version = self._resolve_tls_version(version_name)
            if version is None:
                logger.warning("unknown tls_version %r; using paho default", version_name)
            else:
                kwargs["tls_version"] = version
        ciphers = str(cfg.get("ciphers") or "")
        if ciphers:
            kwargs["ciphers"] = ciphers

        insecure = bool(cfg.get("insecure_skip_verify", False))
        if insecure:
            kwargs["cert_reqs"] = ssl.CERT_NONE

        client.tls_set(**kwargs)
        if insecure and hasattr(client, "tls_insecure_set"):
            client.tls_insecure_set(True)
        logger.info(
            "DJI MQTT TLS configured: port=%s auth=%s ca=%s client_cert=%s "
            "insecure=%s", self.broker_port, auth, bool(ca),
            "certfile" in kwargs, insecure)
        return True

    # ------------------------------------------------------------------ wpml
    def _wpml_cfg(self) -> Dict[str, Any]:
        return self.wpml_config.get("wpml") or {}

    @staticmethod
    def _xml_leaf(tag: str, value: Any, indent: str = "      ") -> str:
        return f"{indent}<wpml:{tag}>{escape(str(value))}</wpml:{tag}>"

    def build_wpml(
        self, waypoints: List[Dict[str, float]],
        task_id: str = "", flight_id: str = "",
    ) -> str:
        """Render a DJI WPML wayline document from normalized waypoints."""
        cfg = self._wpml_cfg()
        mission = cfg.get("mission_config") or {}
        line = cfg.get("wayline") or {}
        wp = cfg.get("waypoint") or {}
        leaf = self._xml_leaf

        kml_ns = str(cfg.get("kml_namespace")
                     or "http://www.opengis.net/kml/2.2")
        wpml_ns = str(cfg.get("wpml_namespace")
                      or "http://www.dji.com/wpmz/1.0.2")
        lines: List[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<kml xmlns="{escape(kml_ns)}" xmlns:wpml="{escape(wpml_ns)}">',
            "  <Document>",
            "    <wpml:missionConfig>",
        ]
        mission_tags = (
            ("fly_to_wayline_mode", "flyToWaylineMode"),
            ("finish_action", "finishAction"),
            ("exit_on_rc_lost", "exitOnRCLost"),
            ("execute_rc_lost_action", "executeRCLostAction"),
            ("take_off_security_height_m", "takeOffSecurityHeight"),
            ("global_transitional_speed_m_s", "globalTransitionalSpeed"),
        )
        for key, tag in mission_tags:
            if key in mission:
                lines.append(leaf(tag, mission[key]))
        for group, pairs in (
            ("drone", (("drone_enum_value", "droneEnumValue"),
                       ("drone_sub_enum_value", "droneSubEnumValue"))),
            ("payload", (("payload_enum_value", "payloadEnumValue"),
                         ("payload_sub_enum_value", "payloadSubEnumValue"))),
        ):
            if any(key in mission for key, _ in pairs):
                lines.append(f"      <wpml:{group}Info>")
                for key, tag in pairs:
                    if key in mission:
                        lines.append(leaf(tag, mission[key], "        "))
                lines.append(f"      </wpml:{group}Info>")
        lines += ["    </wpml:missionConfig>", "    <Folder>"]
        for key, tag in (("template_id", "templateId"),
                         ("wayline_id", "waylineId"),
                         ("auto_flight_speed_m_s", "autoFlightSpeed")):
            if key in line:
                lines.append(leaf(tag, line[key]))
        if task_id:
            lines.append(leaf("waylineName", task_id))
        if flight_id:
            lines.append(leaf("missionName", flight_id))
        lines += [
            "      <wpml:waylineCoordinateSysParam>",
            leaf("coordinateMode", line.get("coordinate_mode", "WGS84"), "        "),
            leaf("positioningType", line.get("positioning_type", "GPS"), "        "),
            leaf("heightMode",
                 line.get("height_mode", "relativeToStartPoint"), "        "),
            "      </wpml:waylineCoordinateSysParam>",
        ]
        actions = wp.get("actions") or []
        for idx, waypoint in enumerate(waypoints):
            alt = float(waypoint.get("alt", 0.0))
            lines += [
                "      <Placemark>",
                leaf("index", idx),
                leaf("executeHeight", alt),
            ]
            if "speed_m_s" in wp:
                lines.append(leaf("waypointSpeed", wp["speed_m_s"]))
            lines += [
                "        <wpml:waypointHeadingParam>",
                leaf("waypointHeadingMode",
                     wp.get("heading_mode", "followWayline"), "          "),
                "        </wpml:waypointHeadingParam>",
                "        <wpml:waypointTurnParam>",
                leaf("waypointTurnMode",
                     wp.get("turn_mode", "smooth"), "          "),
            ]
            if "turn_radius_m" in wp:
                lines.append(
                    leaf("waypointTurnRadius", wp["turn_radius_m"], "          "))
            lines.append("        </wpml:waypointTurnParam>")
            for action in actions:
                if isinstance(action, dict):
                    lines.append("        <wpml:action>")
                    for key, value in action.items():
                        lines.append(leaf(str(key), value, "          "))
                    lines.append("        </wpml:action>")
            lines += [
                "        <Point>",
                f"          <coordinates>{waypoint['lng']},{waypoint['lat']},{alt}</coordinates>",
                "        </Point>",
                "      </Placemark>",
            ]
        lines += ["    </Folder>", "  </Document>", "</kml>", ""]
        return "\n".join(lines)

    def generate_kmz(
        self, waypoints: List[Dict[str, float]], task_id: str,
        flight_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Write a WPML KMZ into the configured data dir; return metadata."""
        cfg = self._wpml_cfg()
        kmz_cfg = cfg.get("kmz") or {}
        out_dir = Path(str(kmz_cfg.get("output_dir") or "data/kmz"))
        if not out_dir.is_absolute():
            out_dir = _BACKEND_ROOT / out_dir
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            wpl_name = str(cfg.get("file_name") or "wpl211.xml")
            wpl = self.build_wpml(waypoints, task_id, flight_id)
            compression = (zipfile.ZIP_DEFLATED
                           if str(kmz_cfg.get("compression") or "deflate").lower()
                           == "deflate" else zipfile.ZIP_STORED)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression) as zf:
                zf.writestr(wpl_name, wpl.encode("utf-8"))
                if bool(kmz_cfg.get("include_doc_kml", False)):
                    zf.writestr("doc.kml", wpl.encode("utf-8"))
            payload = buf.getvalue()
            path = out_dir / f"{task_id}.kmz"
            path.write_bytes(payload)
            meta = {
                "path": str(path),
                "filename": path.name,
                "wpml_file": wpl_name,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "waypoint_count": len(waypoints),
                "created_at": time.time(),
            }
            logger.info("WPML KMZ generated: %s (%d bytes)",
                        path.name, len(payload))
            return meta
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            logger.warning("WPML KMZ generation failed for %s: %s", task_id, exc)
            return None

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
        self._tls_active = self._configure_tls(client)
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
        payload_data = payload.get("data")
        # OSD/state messages carry fields at the root; services messages
        # wrap them in ``data``. Accept both shapes.
        data = payload_data if isinstance(payload_data, dict) else payload
        if method == METHOD_TOPO:
            self.topology = data
        elif method == METHOD_TASK_PROGRESS:
            self._handle_mission_progress(data)
        elif msg.topic.endswith("/osd"):
            self.parse_osd(data)
            self.handle_drc_ack(data)
        elif msg.topic.endswith("/state") or msg.topic.endswith("/events"):
            self.handle_drc_ack(data)
        elif msg.topic.endswith("/services_reply"):
            self._handle_services_reply(payload, topic=msg.topic)

    # --------------------------------------------------- services reply
    def _resolve_calibration_reply(
        self, topic: str, payload: Dict[str, Any],
    ) -> Optional[Tuple[str, str]]:
        """Return (drone_sn, item) if payload is a calibration services_reply.

        Device replies do not always echo ``item`` / ``drone_sn``, so requests
        are correlated by ``bid`` / ``tid`` when those fields are present.
        """
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return None
        method = str(payload.get("method") or data.get("method") or "")
        is_calibration = "calibrat" in method.lower()

        pending = None
        for key in ("bid", "tid"):
            corr = payload.get(key)
            if corr and corr in self._pending_calibration:
                pending = self._pending_calibration[corr]
                break
        if not (is_calibration or pending):
            return None

        sn = data.get("drone_sn") or data.get("sn") or data.get("device_sn")
        item = data.get("item") or data.get("calibration_item")
        if pending is not None:
            sn = sn or pending[0]
            item = item or pending[1]
            # bid and tid point to the same tuple object — drop both entries.
            for key, value in list(self._pending_calibration.items()):
                if value is pending:
                    del self._pending_calibration[key]
        if not sn or not item:
            return None
        return str(sn), str(item)

    @staticmethod
    def _parse_calibration_progress(
        data: Dict[str, Any],
    ) -> Tuple[str, float, str]:
        """Map a device calibration reply to (state, progress, message)."""
        result = data.get("result", data.get("code"))
        message = str(data.get("message") or data.get("msg")
                      or data.get("reason") or "")
        raw_progress = data.get("progress")
        try:
            progress = float(raw_progress) if raw_progress is not None else 0.0
        except (TypeError, ValueError):
            progress = 0.0
        if 0 < progress <= 1.0:  # some devices report 0..1 instead of 0..100
            progress *= 100.0
        progress = max(0.0, min(100.0, progress))

        if result not in (None, 0, "0", "success", "ok", "OK"):
            return "failed", progress, message or f"device result={result}"

        state_raw = data.get("state", data.get("status",
                             data.get("calibration_state")))
        if isinstance(state_raw, str):
            state_map = {
                "idle": "idle", "pending": "idle", "ready": "idle",
                "running": "running", "in_progress": "running",
                "calibrating": "running", "doing": "running",
                "success": "success", "succeed": "success", "done": "success",
                "complete": "success", "completed": "success",
                "failed": "failed", "fail": "failed", "error": "failed",
                "cancelled": "cancelled", "canceled": "cancelled",
            }
            state = state_map.get(state_raw.lower(), state_raw.lower())
        elif state_raw is not None:
            try:
                code = int(state_raw)
                state = {0: "idle", 1: "running", 2: "success",
                         3: "failed", 4: "cancelled"}.get(code, "running")
            except (TypeError, ValueError):
                state = "running"
        else:
            state = "running" if progress < 100 else "success"

        if progress >= 100 and state not in ("failed", "cancelled"):
            state = "success"
        return state, progress, message

    def _handle_services_reply(
        self, payload: Dict[str, Any], topic: str = "",
    ) -> None:
        """Route a DJI services_reply to the calibration state machine."""
        resolved = self._resolve_calibration_reply(topic, payload)
        if resolved is None:
            return
        sn, item = resolved
        data = payload.get("data") or {}
        state, progress, message = self._parse_calibration_progress(data)
        self.update_calibration(
            sn, item, state=state, progress=progress, message=message)
        logger.info(
            "DJI calibration reply: sn=%s item=%s state=%s progress=%.1f%%",
            sn, item, state, progress)

    # ------------------------------------------------------------- commands
    def publish_service(self, method: str, data: Dict[str, Any]) -> bool:
        """Send a cloud -> device service call on ``thing/product/{sn}/services``."""
        topic = self.topic(TOPIC_SERVICES)
        msg = envelope(method, data)
        if method == METHOD_CALIBRATION and self.mode == "cloud":
            # Replies may omit item/drone_sn; keep both correlation ids so the
            # reply handler can recover which aircraft/item was commanded.
            pending = (
                str(data.get("drone_sn") or self.gateway_sn),
                str(data.get("item") or ""),
            )
            self._pending_calibration[msg["bid"]] = pending
            self._pending_calibration[msg["tid"]] = pending
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
                           flight_id: Optional[str] = None,
                           task_id: Optional[str] = None) -> bool:
        """Prepare a waypoint mission with a generated WPML KMZ attached."""
        task_id = task_id or str(uuid.uuid4())
        flight_id = flight_id or str(uuid.uuid4())
        normalized = self._normalize_waypoints(waypoints)
        now = time.time()
        kmz = self.generate_kmz(normalized, task_id, flight_id)
        slot: Dict[str, Any] = {
            "task_id": task_id, "flight_id": flight_id,
            "drone_sn": drone_sn, "waypoints": normalized,
            "idx": 0, "state": "prepared", "progress": 0.0,
            "message": "任务已准备，等待执行",
            "created_at": now, "updated_at": now,
        }
        if kmz:
            slot["kmz"] = kmz
        self._missions[task_id] = slot
        self._mission_by_sn[str(drone_sn)] = task_id
        payload: Dict[str, Any] = {
            "flight_id": flight_id,
            "task_id": task_id,
            "task_type": 0,
            "drone_sn": drone_sn,
            # Kept for mock/tests; real Cloud API consumes the KMZ reference.
            "waypoints": normalized,
        }
        if kmz:
            payload["kmz_file"] = kmz["filename"]
            payload["kmz_sha256"] = kmz["sha256"]
        return self.publish_service(METHOD_TASK_PREPARE, payload)

    @staticmethod
    def _task_data(task_id: str, slot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Include drone_sn so mock/cloud handlers can resolve the aircraft."""
        data: Dict[str, Any] = {"task_id": task_id}
        if slot and slot.get("drone_sn"):
            data["drone_sn"] = slot["drone_sn"]
        return data

    def flighttask_execute(self, task_id: str, flight_id: str) -> bool:
        tid, slot = self._resolve_task(task_id)
        if tid:
            self._set_mission_state(tid, "running", "任务执行中")
        data = self._task_data(task_id, slot)
        data["flight_id"] = flight_id
        return self.publish_service(METHOD_TASK_EXECUTE, data)

    def flighttask_pause(self, task_id: str) -> bool:
        tid, slot = self._resolve_task(task_id)
        if tid:
            self._record_breakpoint(tid, source="local")
            self._set_mission_state(tid, "paused", "任务已暂停")
        return self.publish_service(
            METHOD_TASK_PAUSE, self._task_data(task_id, slot))

    def flighttask_resume(
        self, task_id: str, resume_from: Optional[int] = None,
    ) -> bool:
        tid, slot = self._resolve_task(task_id)
        if tid is None:
            return self.publish_service(
                METHOD_TASK_RESUME, self._task_data(task_id, slot))
        bp = slot.get("breakpoint")
        if resume_from is not None:
            bp = max(0, int(resume_from))
            slot["breakpoint"] = bp
            slot["breakpoint_source"] = "manual"
            slot["breakpoint_at"] = time.time()
        if bp is None:
            bp = self._record_breakpoint(tid, source="local")
        slot["resume_from"] = int(bp or 0)
        info = self._task_data(task_id, slot)
        field = str(self._mission_cfg().get("resume_field")
                    or "resume_from_waypoint")
        info[field] = int(bp or 0)
        self._set_mission_state(tid, "running", "任务已恢复")
        return self.publish_service(METHOD_TASK_RESUME, info)

    def flighttask_cancel(self, task_id: str) -> bool:
        tid, slot = self._resolve_task(task_id)
        if tid:
            self._set_mission_state(tid, "cancelled", "任务已取消")
        return self.publish_service(
            METHOD_TASK_CANCEL, self._task_data(task_id, slot))

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
        cfg = self._drc_cfg()
        wrap = max(1, int(cfg.get("seq_wrap", 65536) or 65536))
        self._drc_seq = (self._drc_seq + 1) % wrap
        seq = self._drc_seq
        axes = {
            "throttle": throttle, "yaw": yaw,
            "pitch": pitch, "roll": roll,
        }
        drc_value = pack_drc(**axes)
        topic = self.topic(TOPIC_DRC)  # gateway (Dock) topic; drone in data
        msg = envelope(METHOD_DRC, {
            "drone_sn": drone_sn,
            "drc": drc_value,
            "drc_seq": seq,
            "control_source": "skymaster",
        }, need_reply=0)
        sent_at = time.time()
        if self.mode == "mock":
            self.last_drc[drone_sn] = unpack_drc(drc_value)
            self._mock_state[drone_sn] = "DRC"
            self._drc_pending[drone_sn] = {
                "seq": seq, "axes": axes, "sent_at": sent_at,
            }
            if self.on_message:
                self.on_message(topic, msg)
            return True
        if not self._client or not self._connected:
            logger.warning("send_drc: MQTT not connected")
            return False
        info = self._client.publish(topic, json.dumps(msg), qos=0)
        ok = info.rc == mqtt.MQTT_ERR_SUCCESS  # type: ignore[union-attr]
        if ok:
            self._drc_pending[drone_sn] = {
                "seq": seq, "axes": axes, "sent_at": sent_at,
            }
        else:
            self.last_drc_ack[drone_sn] = {
                "seq": seq, "axes": axes, "state": "send_failed",
                "latency_ms": None, "at": sent_at,
            }
        return ok

    # ------------------------------------------------------------- mission
    @staticmethod
    def _load_json_config(
        path: Optional[str], default_path: Path, label: str,
    ) -> Dict[str, Any]:
        """Load a standalone JSON config; tolerate missing/corrupt files."""
        cfg_path = Path(path or default_path)
        try:
            with cfg_path.open("r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if not isinstance(cfg, dict):
                raise ValueError(f"{label} must be a JSON object")
            return cfg
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("%s %s unavailable: %s; using empty defaults",
                           label, cfg_path, exc)
            return {}

    def _load_mission_routes(self, path: Optional[str] = None) -> List[Dict[str, Any]]:
        cfg_path = Path(path or DEFAULT_MISSION_ROUTES)
        try:
            with cfg_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            routes = data.get("routes") if isinstance(data, dict) else None
            if isinstance(routes, list):
                return [r for r in routes if isinstance(r, dict)]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("mission routes %s unavailable: %s", cfg_path, exc)
        return []

    def _mission_cfg(self) -> Dict[str, Any]:
        return self.mission_config.get("mission") or {}

    @staticmethod
    def _pick_field(data: Dict[str, Any], names: List[str]) -> Any:
        for name in names:
            if data.get(name) is not None:
                return data[name]
        return None

    def _normalize_waypoints(
        self, waypoints: List[Dict[str, Any]],
    ) -> List[Dict[str, float]]:
        cfg = self._mission_cfg()
        default_alt = float(cfg.get("default_alt_m", 80.0))
        limit = max(1, int(cfg.get("max_waypoints", 100) or 100))
        out: List[Dict[str, float]] = []
        for w in (waypoints or [])[:limit]:
            try:
                out.append({
                    "lat": float(w["lat"]),
                    "lng": float(w.get("lng", w.get("lon"))),
                    "alt": float(w.get("alt", default_alt)),
                })
            except (KeyError, TypeError, ValueError):
                logger.warning("skip invalid waypoint: %r", w)
        return out

    def mission_routes(self) -> List[Dict[str, Any]]:
        """Preset patrol routes loaded from the standalone JSON file."""
        return [dict(route) for route in self._mission_routes]

    def _resolve_task(
        self, task_id: Optional[str] = None, drone_sn: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Resolve a task by id, latest-per-aircraft, or single active task."""
        if task_id and task_id in self._missions:
            return task_id, self._missions[task_id]
        if drone_sn:
            tid = self._mission_by_sn.get(str(drone_sn))
            if tid and tid in self._missions:
                return tid, self._missions[tid]
        if len(self._missions) == 1:
            tid = next(iter(self._missions))
            return tid, self._missions[tid]
        return None, None

    def _set_mission_state(
        self, task_id: str, state: str, message: str = "",
        progress: Optional[float] = None,
    ) -> None:
        slot = self._missions.get(task_id)
        if slot is None:
            return
        slot["state"] = state
        if progress is not None:
            slot["progress"] = max(0.0, min(100.0, float(progress)))
        if message:
            slot["message"] = message
        slot["updated_at"] = time.time()

    def create_mission(
        self, drone_sn: str, waypoints: List[Dict[str, Any]],
        flight_id: Optional[str] = None,
    ) -> Optional[str]:
        """Prepare a mission and return its task_id (None if not dispatched)."""
        normalized = self._normalize_waypoints(waypoints)
        if not normalized:
            return None
        task_id = str(uuid.uuid4())
        ok = self.flighttask_prepare(
            drone_sn, normalized, flight_id=flight_id, task_id=task_id)
        if not ok and self.mode != "mock":
            return None
        return task_id

    # ------------------------------------------------------------ breakpoint
    def _record_breakpoint(
        self, task_id: str, raw: Any = None, source: str = "local",
    ) -> Optional[int]:
        """Persist the last confirmed waypoint index for resume.

        Device reports use the configured field names and offset; local
        pauses use the task's own ``idx``. Values never move backwards.
        """
        slot = self._missions.get(task_id)
        if slot is None:
            return None
        cfg = self._mission_cfg()
        value: Optional[int] = None
        if raw is not None:
            try:
                value = int(float(raw))
            except (TypeError, ValueError):
                value = None
            if value is not None:
                offset = int(cfg.get("breakpoint_offset", 0) or 0)
                value = max(0, value - offset)
        if value is None:
            try:
                value = int(slot.get("idx", 0) or 0)
            except (TypeError, ValueError):
                value = 0
        current = slot.get("breakpoint")
        if current is not None:
            value = max(int(current), value)
        total = len(slot.get("waypoints") or [])
        if total > 0:
            value = min(value, total)
        slot["breakpoint"] = value
        slot["breakpoint_source"] = source
        slot["breakpoint_at"] = time.time()
        slot["updated_at"] = time.time()
        return value

    def breakpoint_status(
        self, task_id: Optional[str] = None, drone_sn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resume points with staleness, for UI and manual intervention."""
        items: List[Dict[str, Any]] = []
        cfg = self._mission_cfg()
        stale_s = float(cfg.get("breakpoint_stale_s", 3600) or 3600)
        now = time.time()
        for slot in self._missions.values():
            if task_id and slot.get("task_id") != task_id:
                continue
            if drone_sn and slot.get("drone_sn") != drone_sn:
                continue
            if "breakpoint" not in slot:
                continue
            at = float(slot.get("breakpoint_at") or 0)
            items.append({
                "task_id": slot.get("task_id"),
                "drone_sn": slot.get("drone_sn"),
                "state": slot.get("state"),
                "breakpoint": slot["breakpoint"],
                "waypoint_count": len(slot.get("waypoints") or []),
                "source": slot.get("breakpoint_source"),
                "breakpoint_at": at,
                "stale": bool(at and now - at > stale_s),
                "resume_from": slot.get("resume_from"),
            })
        items.sort(key=lambda x: x["breakpoint_at"], reverse=True)
        return {
            "breakpoints": items,
            "config": {
                "resume_field": str(cfg.get("resume_field")
                                     or "resume_from_waypoint"),
                "stale_s": stale_s,
            },
        }

    def mission_status(
        self, drone_sn: Optional[str] = None, task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        for slot in self._missions.values():
            if drone_sn and slot.get("drone_sn") != drone_sn:
                continue
            if task_id and slot.get("task_id") != task_id:
                continue
            items.append(dict(slot))
        items.sort(key=lambda m: m.get("created_at", 0.0), reverse=True)
        return {
            "missions": items,
            "routes": self.mission_routes(),
            "config": self.mission_config,
        }

    def _parse_mission_progress(
        self, data: Dict[str, Any],
    ) -> Tuple[str, float, str]:
        """Map a device flighttask_progress payload to state/progress/message."""
        cfg = self._mission_cfg()
        result = self._pick_field(data, cfg.get("result_fields") or [])
        state_raw = self._pick_field(data, cfg.get("state_fields") or [])
        progress_raw = self._pick_field(data, cfg.get("progress_fields") or [])
        message = str(self._pick_field(
            data, cfg.get("message_fields") or []) or "")
        try:
            progress = float(progress_raw) if progress_raw is not None else 0.0
        except (TypeError, ValueError):
            progress = 0.0
        if 0 < progress <= 1.0:
            progress *= 100.0
        progress = max(0.0, min(100.0, progress))

        if result not in (None, 0, "0", "success", "ok", "OK"):
            return "failed", progress, message or f"device result={result}"

        state_map = cfg.get("state_map") or {}
        numeric = cfg.get("numeric_state_map") or {}
        if isinstance(state_raw, str):
            state = state_map.get(state_raw.lower(), state_raw.lower())
        elif state_raw is not None:
            try:
                state = numeric.get(str(int(state_raw)), "running")
            except (TypeError, ValueError):
                state = "running"
        elif progress >= 100:
            state = "success"
        else:
            state = "running"
        if progress >= 100 and state not in ("failed", "cancelled"):
            state = "success"
        return state, progress, message

    def _handle_mission_progress(self, data: Dict[str, Any]) -> None:
        """Route a device progress report into the mission state machine."""
        if not isinstance(data, dict):
            return
        cfg = self._mission_cfg()
        task_raw = self._pick_field(data, cfg.get("task_id_fields") or [])
        sn_raw = data.get("drone_sn") or data.get("sn")
        tid, _ = self._resolve_task(
            str(task_raw) if task_raw else None,
            str(sn_raw) if sn_raw else None,
        )
        if tid is None:
            return
        state, progress, message = self._parse_mission_progress(data)
        self._record_breakpoint(
            tid, self._pick_field(data, cfg.get("breakpoint_fields") or []),
            source="device")
        self._set_mission_state(tid, state, message, progress)
        logger.info("DJI mission progress: task=%s state=%s progress=%.1f%%",
                    tid, state, progress)

    def _advance_mock_missions(self) -> None:
        """Advance one waypoint per tick for FLYING mock missions."""
        for sn, mock in list(self._mock_mission.items()):
            if self._mock_state.get(sn) != "FLYING":
                continue
            tid, slot = self._resolve_task(drone_sn=sn)
            if slot is None:
                continue
            total = len(slot.get("waypoints") or [])
            if total <= 0:
                continue
            idx = min(total, int(mock.get("idx", 0)) + 1)
            mock["idx"] = idx
            slot["idx"] = idx
            slot["progress"] = round(idx / total * 100.0, 1)
            slot["updated_at"] = time.time()
            if idx >= total:
                self._set_mission_state(tid, "success", "航线执行完成", 100.0)

    # -------------------------------------------------------------- control
    @staticmethod
    def _load_control_config(path: Optional[str] = None) -> Dict[str, Any]:
        """Load DRC ack timing / reply field names from the standalone JSON."""
        cfg_path = Path(path or DEFAULT_CONTROL_CONFIG)
        try:
            with cfg_path.open("r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if not isinstance(cfg, dict):
                raise ValueError("control config must be a JSON object")
            return cfg
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "control config %s unavailable: %s; using empty defaults",
                cfg_path, exc)
            return {"drc": {}}

    def _drc_cfg(self) -> Dict[str, Any]:
        return self.control_config.get("drc") or {}

    def handle_drc_ack(self, data: Dict[str, Any]) -> bool:
        """Record a device ack for the most recent DRC command.

        Firmware variants name the sequence field differently; the accepted
        names come from ``config/dji_control.json``.
        """
        if not isinstance(data, dict):
            return False
        nested = data.get("data")
        candidates = [data]
        if isinstance(nested, dict):
            candidates.append(nested)

        seq = None
        for field in self._drc_cfg().get("ack_fields") or []:
            for src in candidates:
                if src.get(field) is not None:
                    try:
                        seq = int(src[field])
                    except (TypeError, ValueError):
                        continue
                    break
            if seq is not None:
                break
        if seq is None:
            return False

        sn = data.get("sn") or data.get("drone_sn")
        if not sn and isinstance(nested, dict):
            sn = nested.get("sn") or nested.get("drone_sn")
        sn = str(sn or "")
        if not sn:
            for key, pending in self._drc_pending.items():
                if pending.get("seq") == seq:
                    sn = key
                    break
        if not sn:
            return False
        pending = self._drc_pending.get(sn)
        if pending is None:
            return False
        if int(pending.get("seq", -1)) != seq:
            logger.debug("stale DRC ack for %s: seq=%s expected=%s",
                         sn, seq, pending.get("seq"))
            return False

        now = time.time()
        self.last_drc_ack[sn] = {
            "seq": seq,
            "axes": dict(pending["axes"]),
            "state": "acked",
            "latency_ms": round((now - float(pending["sent_at"])) * 1000.0, 1),
            "at": now,
        }
        self._drc_pending.pop(sn, None)
        return True

    def _advance_drc_ack(self) -> None:
        """Mock device ack after the configured delay."""
        raw_delay = self._drc_cfg().get("ack_delay_ms")
        delay_s = float(120 if raw_delay is None else raw_delay) / 1000.0
        now = time.time()
        for sn, pending in list(self._drc_pending.items()):
            if now - float(pending["sent_at"]) >= delay_s:
                self.handle_drc_ack({
                    "sn": sn,
                    "drc_ack_seq": pending["seq"],
                    "control_ack": 0,
                })

    def _expire_drc_pending(self) -> None:
        """Mark unacknowledged cloud-mode commands as timed out."""
        raw_timeout = self._drc_cfg().get("ack_timeout_ms")
        timeout_s = float(3000 if raw_timeout is None else raw_timeout) / 1000.0
        now = time.time()
        for sn, pending in list(self._drc_pending.items()):
            if now - float(pending["sent_at"]) > timeout_s:
                self.last_drc_ack[sn] = {
                    "seq": pending["seq"],
                    "axes": dict(pending["axes"]),
                    "state": "timeout",
                    "latency_ms": None,
                    "at": now,
                }
                self._drc_pending.pop(sn, None)
                logger.warning("DRC ack timeout for %s seq=%s",
                               sn, pending["seq"])

    def drc_link_status(self) -> Dict[str, Any]:
        """Command / ack link status for the joystick panel."""
        raw_timeout = self._drc_cfg().get("ack_timeout_ms")
        timeout_ms = float(3000 if raw_timeout is None else raw_timeout)
        now = time.time()
        pending = {}
        for sn, p in self._drc_pending.items():
            age_ms = round((now - float(p["sent_at"])) * 1000.0, 1)
            pending[sn] = {
                "seq": p["seq"], "axes": p["axes"],
                "age_ms": age_ms, "timed_out": age_ms > timeout_ms,
            }
        return {
            "seq": self._drc_seq,
            "last_ack": self.last_drc_ack,
            "pending": pending,
            "ack_timeout_ms": timeout_ms,
        }

    # ---------------------------------------------------------- calibration
    @staticmethod
    def _load_calibration_config(path: Optional[str] = None) -> Dict[str, Any]:
        """Load sensor durations and RC wizard steps from the standalone JSON."""
        cfg_path = Path(path or DEFAULT_CALIBRATION_CONFIG)
        try:
            with cfg_path.open("r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            if not isinstance(cfg, dict):
                raise ValueError("calibration config must be a JSON object")
            return cfg
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "calibration config %s unavailable: %s; using empty defaults",
                cfg_path, exc)
            return {
                "sensor_calibration": {},
                "rc_calibration": {"deadzone": 0.05, "steps": []},
            }

    def _load_rc_calibration(self) -> Dict[str, Dict[str, Any]]:
        try:
            with self.rc_calibration_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save_rc_calibration(self) -> None:
        self.rc_calibration_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.rc_calibration_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self._rc_calibration, fh, ensure_ascii=False, indent=2)
        tmp.replace(self.rc_calibration_path)

    def calibration_items(self) -> List[Dict[str, Any]]:
        """Sensor calibration items plus the manual RC wizard entry."""
        items: List[Dict[str, Any]] = []
        for key, meta in (self.calibration_config.get("sensor_calibration") or {}).items():
            items.append({
                "key": key, "kind": "sensor",
                "label": meta.get("label", key),
                "duration_s": meta.get("duration_s", 0),
                "hint": meta.get("hint", ""),
            })
        items.append({
            "key": RC_CALIBRATION_ITEM, "kind": "rc", "label": "遥控器摇杆",
            "duration_s": 0, "hint": "按向导采集四轴极值与中位",
        })
        return items

    def calibration_status(self, drone_sn: Optional[str] = None) -> Dict[str, Any]:
        if drone_sn:
            sensors = {drone_sn: {
                item: dict(state)
                for item, state in self._calibration.get(drone_sn, {}).items()
            }}
        else:
            sensors = {
                sn: {item: dict(state) for item, state in items.items()}
                for sn, items in self._calibration.items()
            }
        return {
            "items": self.calibration_items(),
            "sensors": sensors,
            "rc": self._rc_calibration,
            "config": self.calibration_config,
        }

    def start_calibration(self, drone_sn: str, item: str) -> bool:
        """Start a sensor calibration, or open the manual RC wizard."""
        state = self._calibration.setdefault(drone_sn, {})
        if item == RC_CALIBRATION_ITEM:
            state[item] = {
                "state": "manual", "progress": 0,
                "message": "等待摇杆六方向采集", "updated_at": time.time(),
            }
            return True
        meta = (self.calibration_config.get("sensor_calibration") or {}).get(item)
        if meta is None:
            logger.warning("start_calibration: unknown item %r", item)
            return False
        state[item] = {
            "state": "running", "progress": 0,
            "duration_s": float(meta.get("duration_s", 10)),
            "message": meta.get("hint", ""),
            "started_at": time.time(), "updated_at": time.time(),
        }
        return self.publish_service(METHOD_CALIBRATION, {
            "drone_sn": drone_sn, "item": item, "action": "start",
        })

    def cancel_calibration(self, drone_sn: str, item: str) -> bool:
        state = self._calibration.get(drone_sn, {}).get(item)
        if state is None:
            return False
        state.update(state="cancelled", progress=0, message="已取消",
                     updated_at=time.time())
        self.publish_service(METHOD_CALIBRATION, {
            "drone_sn": drone_sn, "item": item, "action": "cancel",
        })
        return True

    def update_calibration(self, drone_sn: str, item: str, *, state: str,
                           progress: Optional[float] = None,
                           message: str = "") -> None:
        """Apply a services_reply progress update (cloud mode)."""
        slot = self._calibration.setdefault(drone_sn, {}).setdefault(item, {})
        slot["state"] = state
        if progress is not None:
            slot["progress"] = max(0.0, min(100.0, float(progress)))
        slot["message"] = message
        slot["updated_at"] = time.time()

    def set_rc_calibration(self, drone_sn: str,
                           axes: Dict[str, Dict[str, float]],
                           deadzone: Optional[float] = None) -> bool:
        """Persist RC stick endpoints to a standalone JSON and mark RC done."""
        if any(axis not in axes for axis in RC_AXES):
            return False
        rc_cfg = self.calibration_config.get("rc_calibration") or {}
        dz = rc_cfg.get("deadzone", 0.05) if deadzone is None else deadzone
        self._rc_calibration[drone_sn] = {
            "axes": {
                axis: {
                    "min": float(axes[axis]["min"]),
                    "center": float(axes[axis]["center"]),
                    "max": float(axes[axis]["max"]),
                }
                for axis in RC_AXES
            },
            "deadzone": float(dz),
            "updated_at": time.time(),
        }
        self._save_rc_calibration()
        state = self._calibration.setdefault(drone_sn, {}).setdefault(
            RC_CALIBRATION_ITEM, {})
        state.update(state="success", progress=100, message="摇杆校准已保存",
                     updated_at=time.time())
        return True

    def apply_rc_axis(self, drone_sn: str, axis: str, raw: float) -> float:
        """Map a raw stick value through saved endpoints and deadzone."""
        saved = self._rc_calibration.get(drone_sn) or {}
        cal = (saved.get("axes") or {}).get(axis)
        if cal is None or cal["max"] <= cal["min"]:
            return max(-1.0, min(1.0, float(raw)))
        center = float(cal["center"])
        span = (cal["max"] - center) if float(raw) >= center else (center - cal["min"])
        if span <= 0:
            return 0.0
        v = (float(raw) - center) / span
        dz = float(saved.get("deadzone", 0.0))
        if abs(v) < dz:
            return 0.0
        return round(max(-1.0, min(1.0, v)), 4)

    def _advance_calibration(self, dt: float) -> None:
        """Advance mock sensor calibration progress."""
        for items in self._calibration.values():
            for state in items.values():
                if state.get("state") != "running":
                    continue
                duration = float(state.get("duration_s", 0) or 0)
                if duration <= 0:
                    continue
                state["progress"] = min(
                    100.0, float(state.get("progress", 0)) + dt / duration * 100.0)
                state["updated_at"] = time.time()
                if state["progress"] >= 100.0:
                    state.update(state="success", message="校准完成",
                                 updated_at=time.time())

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
        elif method == METHOD_CALIBRATION:
            logger.info("[MOCK] calibration %s for %s", data.get("item"), sn)

    def mock_tick(self, dt: float = 0.5) -> List[Dict[str, Any]]:
        """Advance mock simulation by ``dt`` seconds; return OSD payloads."""
        self._mock_t += dt
        self._advance_calibration(dt)
        self._advance_drc_ack()
        self._advance_mock_missions()
        frames = []
        for i in range(self.mock_drones):
            osd = self._mock_osd(i)
            frames.append(osd)
            self.parse_osd(osd)
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
                self._expire_drc_pending()
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
