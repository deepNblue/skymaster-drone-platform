"""WPML / KMZ wayline generation tests (config-driven, no hardcoded parameters)."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.dji_cloud_connector import DJICloudConnector

SN = "MOCKM300-01"
WPS = [
    {"lat": 22.81, "lng": 108.31, "alt": 80.0},
    {"lat": 22.82, "lng": 108.32, "alt": 90.0},
]
KML_NS = "http://www.opengis.net/kml/2.2"
WPML_NS = "http://www.dji.com/wpmz/1.0.2"


@pytest.fixture
def conn():
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="mock", mock_drones=1)
    c.connect()
    return c


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_OPTIONAL", "true")
    from app.config import settings
    monkeypatch.setattr(settings, "auth_optional", True)
    return TestClient(app)


@pytest.fixture
def mock_connector():
    c = DJICloudConnector(gateway_sn="TESTDOCK", mode="mock", mock_drones=1)
    c.connect()
    old = getattr(app.state, "dji_connector", None)
    app.state.dji_connector = c
    yield c
    if old is None and hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    else:
        app.state.dji_connector = old


def test_loads_default_wpml_config(conn):
    cfg = conn._wpml_cfg()
    assert cfg["file_name"] == "wpl211.xml"
    assert cfg["mission_config"]["finish_action"]
    assert cfg["wayline"]["coordinate_mode"] == "WGS84"
    assert cfg["kmz"]["output_dir"] == "data/kmz"


def test_build_wpml_is_valid_xml_and_config_driven(conn):
    xml = conn.build_wpml(WPS, "task-1", "flight-1")
    root = ET.fromstring(xml)
    ns = {"kml": KML_NS, "wpml": WPML_NS}
    assert root.tag == f"{{{KML_NS}}}kml"
    assert len(root.findall(".//kml:Placemark", ns)) == len(WPS)
    cfg = conn._wpml_cfg()
    finish = cfg["mission_config"]["finish_action"]
    assert f"<wpml:finishAction>{finish}</wpml:finishAction>" in xml
    coords = [e.text for e in root.findall(".//kml:coordinates", ns)]
    assert coords == ["108.31,22.81,80.0", "108.32,22.82,90.0"]
    assert "task-1" in xml and "flight-1" in xml


def test_generate_kmz_packages_wpl_with_metadata(conn):
    meta = conn.generate_kmz(WPS, "kmz-task")
    assert meta["wpml_file"] == "wpl211.xml"
    assert meta["waypoint_count"] == len(WPS)
    raw = Path(meta["path"]).read_bytes()
    assert len(raw) == meta["size_bytes"]
    assert hashlib.sha256(raw).hexdigest() == meta["sha256"]
    assert meta["filename"] == "kmz-task.kmz"
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert zf.namelist() == ["wpl211.xml"]
        assert ET.fromstring(zf.read("wpl211.xml")).tag == f"{{{KML_NS}}}kml"


def test_custom_config_controls_names_actions_and_doc_kml(tmp_path):
    cfg = {"wpml": {
        "file_name": "custom.xml",
        "mission_config": {"finish_action": "land"},
        "wayline": {"auto_flight_speed_m_s": 4.5},
        "waypoint": {"speed_m_s": 3.0, "actions": [
            {"actionActuatorFunc": "takePhoto", "actionGroupId": 1}]},
        "kmz": {"output_dir": str(tmp_path), "include_doc_kml": True,
                "compression": "store"},
    }}
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    c = DJICloudConnector(mode="mock", wpml_config_path=str(cfg_path))

    xml = c.build_wpml(WPS[:1])
    assert "land" in xml
    assert "<wpml:autoFlightSpeed>4.5</wpml:autoFlightSpeed>" in xml
    assert "<wpml:waypointSpeed>3.0</wpml:waypointSpeed>" in xml
    assert "takePhoto" in xml

    meta = c.generate_kmz(WPS, "custom")
    assert meta["wpml_file"] == "custom.xml"
    assert Path(meta["path"]).parent == tmp_path
    with zipfile.ZipFile(meta["path"]) as zf:
        assert set(zf.namelist()) == {"custom.xml", "doc.kml"}
        assert zf.getinfo("custom.xml").compress_type == zipfile.ZIP_STORED


def test_generate_kmz_failure_returns_none(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"wpml": {
        "kmz": {"output_dir": str(blocker)}}}), encoding="utf-8")
    c = DJICloudConnector(mode="mock", wpml_config_path=str(cfg_path))
    assert c.generate_kmz(WPS, "bad") is None


def test_prepare_attaches_kmz_to_slot_and_payload(conn):
    sent = []
    conn.on_message = lambda topic, msg: sent.append(msg)
    tid = conn.create_mission(SN, WPS)
    assert tid
    slot = conn._missions[tid]
    assert slot["kmz"]["waypoint_count"] == len(WPS)
    payload = sent[-1]["data"]
    assert payload["kmz_file"] == slot["kmz"]["filename"]
    assert payload["kmz_sha256"] == slot["kmz"]["sha256"]


def test_status_exposes_kmz_metadata(conn):
    tid = conn.create_mission(SN, WPS)
    st = conn.mission_status(task_id=tid)
    kmz = st["missions"][0]["kmz"]
    assert {"filename", "wpml_file", "size_bytes", "sha256"} <= set(kmz)


def test_prepare_status_and_kmz_download_api(client, mock_connector):
    r = client.post("/api/v1/dji/mission/prepare", json={
        "drone_sn": SN, "waypoints": WPS,
    })
    assert r.status_code == 200
    tid = r.json()["task_id"]
    st = client.get("/api/v1/dji/mission/status", params={"task_id": tid})
    kmz = st.json()["missions"][0]["kmz"]
    assert kmz["filename"] == f"{tid}.kmz"

    d = client.get("/api/v1/dji/mission/kmz", params={"task_id": tid})
    assert d.status_code == 200
    assert d.headers["content-type"] == "application/vnd.google-earth.kmz"
    with zipfile.ZipFile(io.BytesIO(d.content)) as zf:
        assert "wpl211.xml" in zf.namelist()
    assert d.content == Path(kmz["path"]).read_bytes()


def test_kmz_download_unknown_task_returns_404(client, mock_connector):
    r = client.get("/api/v1/dji/mission/kmz", params={"task_id": "missing"})
    assert r.status_code == 404
