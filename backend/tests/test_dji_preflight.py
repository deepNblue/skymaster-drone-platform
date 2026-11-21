"""Tests for the data-driven DJI real-device preflight checklist."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.dji_preflight import DJIPreflight


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_OPTIONAL", "true")
    from app.config import settings
    monkeypatch.setattr(settings, "auth_optional", True)
    return TestClient(app)


class _Settings:
    dji_mode = "mock"
    dji_gateway_sn = "MOCKDOCK001"
    dji_broker_host = "127.0.0.1"
    dji_broker_port = 1883
    dji_client_id = ""
    dji_username = ""
    dji_password = ""


def _report(**kw):
    return DJIPreflight(settings=_Settings(), **kw).report()


def test_report_shape_and_counts():
    r = _report()
    assert r["version"]
    assert r["generated_at"]
    assert r["mode"] == "mock"
    assert r["connector_mounted"] is False
    assert [g["id"] for g in r["groups"]] == [
        "link", "tls", "telemetry", "drc", "calibration", "mission", "wpml", "files",
    ]
    s = r["summary"]
    assert s["total"] == sum(s[k] for k in ("pass", "warn", "fail", "manual"))
    assert s["total"] >= 40
    assert s["ready"] is False
    assert "mode_cloud" in s["blocking"]


def test_mock_defaults_are_blocking():
    items = {i["id"]: i for g in _report()["groups"] for i in g["items"]}
    assert items["mode_cloud"]["status"] == "fail"
    assert items["gateway_sn"]["status"] == "fail"
    assert items["broker_host"]["status"] == "fail"
    assert items["gateway_sn"]["value"] == "MOCKDOCK001"
    assert items["tls_enabled"]["status"] == "pass"
    assert items["route_altitude"]["status"] == "pass"
    assert items["kmz_dir"]["status"] == "pass"


def test_manual_items_carry_verify_hint():
    manual = [
        i for g in _report()["groups"] for i in g["items"]
        if i["status"] == "manual"
    ]
    assert len(manual) >= 15
    assert all(i["verify"] for i in manual)


def test_config_files_exist():
    files = [
        i for g in _report()["groups"] if g["id"] == "files" for i in g["items"]
    ]
    assert len(files) == 6
    assert all(i["status"] == "pass" for i in files)
    assert all(i["config_file"] and i["config_file"].endswith(".json") for i in files)


def test_secrets_never_leak():
    class SecretSettings(_Settings):
        dji_username = "workspace-user"
        dji_password = "super-secret-token"

    r = DJIPreflight(settings=SecretSettings()).report()
    dumped = json.dumps(r, ensure_ascii=False)
    assert "super-secret-token" not in dumped
    assert "workspace-user" not in dumped
    items = {i["id"]: i for g in r["groups"] for i in g["items"]}
    assert items["username"]["value"] == "已配置"
    assert items["password"]["status"] == "pass"


def test_markdown_contains_blockers_and_checkboxes():
    p = DJIPreflight(settings=_Settings())
    text = p.markdown()
    assert "# DJI 真机联调核对清单" in text
    assert "## 阻塞项" in text
    assert "- `mode_cloud`" in text
    assert "- [x] **TLS 开关**" in text
    assert "真机核对：" in text


def test_custom_checklist_check_types(tmp_path):
    cfg = {
        "version": "test",
        "placeholder_values": ["TODO", ""],
        "groups": [
            {
                "id": "g", "title": "G",
                "items": [
                    {"id": "eq", "title": "eq", "source": "runtime", "key": "mode",
                     "check": "equals", "expected": "cloud"},
                    {"id": "ph", "title": "ph", "source": "constant", "value": "TODO",
                     "check": "not_placeholder"},
                    {"id": "host", "title": "host", "source": "runtime", "key": "broker_host",
                     "check": "not_local_host"},
                    {"id": "truth", "title": "truth", "source": "constant", "value": False,
                     "check": "truthy"},
                    {"id": "falsy", "title": "falsy", "source": "constant", "value": False,
                     "check": "falsy"},
                    {"id": "secret", "title": "secret", "source": "runtime", "key": "password",
                     "check": "configured", "secret": True},
                    {"id": "dir", "title": "dir", "source": "constant",
                     "value": str(tmp_path / "kmz"), "check": "dir_writable"},
                    {"id": "alt", "title": "alt", "source": "config:routes", "key": "routes",
                     "check": "max_altitude", "expected": 150},
                    {"id": "manual", "title": "manual", "source": "constant", "value": "x",
                     "check": "manual", "verify": "固件核对"},
                ],
            }
        ],
    }
    path = tmp_path / "checklist.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    r = DJIPreflight(settings=_Settings(), config_path=str(path)).report()
    items = {i["id"]: i["status"] for i in r["groups"][0]["items"]}
    assert items == {
        "eq": "fail", "ph": "fail", "host": "fail", "truth": "fail", "falsy": "pass",
        "secret": "fail", "dir": "pass", "alt": "pass", "manual": "manual",
    }
    assert (tmp_path / "kmz").is_dir()


def test_api_preflight_without_connector(client):
    if hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    r = client.get("/api/v1/dji/preflight")
    assert r.status_code == 200
    d = r.json()
    assert d["connector_mounted"] is False
    assert d["summary"]["total"] >= 40


def test_api_preflight_markdown_download(client):
    r = client.get("/api/v1/dji/preflight/markdown")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "dji-preflight-checklist.md" in r.headers["content-disposition"]
    assert "# DJI 真机联调核对清单" in r.text
