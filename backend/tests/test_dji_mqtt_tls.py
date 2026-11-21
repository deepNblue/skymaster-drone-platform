"""MQTT TLS / clientAuth configuration tests (paho replaced by a spy client)."""
from __future__ import annotations

import json
import ssl
import types

import pytest

from app.services import dji_cloud_connector as mod
from app.services.dji_cloud_connector import DJICloudConnector

BASE_CFG = {
    "enabled": True,
    "ports": [8883, 443],
    "ca_certs": "",
    "certfile": "",
    "keyfile": "",
    "client_auth": "none",
    "tls_version": "TLSv1_2",
    "ciphers": "",
    "insecure_skip_verify": False,
}


@pytest.fixture
def fake_mqtt(monkeypatch):
    created = []

    class FakeClient:
        def __init__(self, client_id=None, clean_session=None, **kwargs):
            self.client_id = client_id
            self.tls_calls = []
            self.insecure_calls = []
            self.connect_calls = []
            self.subs = []
            self.credentials = None
            created.append(self)

        def tls_set(self, **kwargs):
            self.tls_calls.append(kwargs)

        def tls_insecure_set(self, value):
            self.insecure_calls.append(value)

        def username_pw_set(self, username, password):
            self.credentials = (username, password)

        def connect(self, host, port, keepalive=30):
            self.connect_calls.append((host, port, keepalive))

        def subscribe(self, topic, qos=0):
            self.subs.append((topic, qos))

    stub = types.ModuleType("fake_mqtt")
    stub.Client = FakeClient
    stub.MQTT_ERR_SUCCESS = 0
    monkeypatch.setattr(mod, "mqtt", stub)
    return created


def build(tmp_path, cfg=None, port=8883):
    path = tmp_path / "tls.json"
    path.write_text(json.dumps({"tls": cfg if cfg is not None else BASE_CFG}),
                    encoding="utf-8")
    c = DJICloudConnector(
        mode="cloud", gateway_sn="TESTDOCK", broker_host="broker.example.com",
        broker_port=port, tls_config_path=str(path),
    )
    c.connect()
    return c


def test_plaintext_port_does_not_enable_tls(tmp_path, fake_mqtt):
    c = build(tmp_path, port=1883)
    assert c._client.tls_calls == []
    assert c._client.connect_calls == [("broker.example.com", 1883, 30)]
    assert c.tls_status()["active"] is False


def test_tls_port_configures_ca_before_connect(tmp_path, fake_mqtt):
    cfg = dict(BASE_CFG, ca_certs="/etc/dji/ca.pem")
    c = build(tmp_path, cfg)
    assert c._client.tls_calls[0]["ca_certs"] == "/etc/dji/ca.pem"
    assert c._client.connect_calls[0][1] == 8883
    assert c.tls_status()["ca_configured"] is True
    assert c.tls_status()["active"] is True


def test_mutual_auth_includes_client_certificate(tmp_path, fake_mqtt):
    cfg = dict(BASE_CFG, client_auth="required",
               certfile="/etc/dji/client.crt", keyfile="/etc/dji/client.key")
    c = build(tmp_path, cfg)
    kw = c._client.tls_calls[0]
    assert kw["certfile"] == "/etc/dji/client.crt"
    assert kw["keyfile"] == "/etc/dji/client.key"
    assert c.tls_status()["client_cert_configured"] is True


def test_mutual_auth_without_cert_degrades_safely(tmp_path, fake_mqtt):
    cfg = dict(BASE_CFG, client_auth="required")
    c = build(tmp_path, cfg)
    kw = c._client.tls_calls[0]
    assert "certfile" not in kw and "keyfile" not in kw
    assert c.tls_status()["client_cert_configured"] is False


def test_insecure_flag_sets_cert_none(tmp_path, fake_mqtt):
    cfg = dict(BASE_CFG, insecure_skip_verify=True, ca_certs="/etc/dji/ca.pem")
    c = build(tmp_path, cfg)
    assert c._client.tls_calls[0]["cert_reqs"] == ssl.CERT_NONE
    assert c._client.insecure_calls == [True]
    assert c.tls_status()["insecure_skip_verify"] is True


def test_tls_version_resolves_to_ssl_enum(tmp_path, fake_mqtt):
    c = build(tmp_path)
    expected = DJICloudConnector._resolve_tls_version("TLSv1_2")
    assert expected is not None
    assert c._client.tls_calls[0]["tls_version"] == expected


def test_ciphers_passed_through(tmp_path, fake_mqtt):
    cfg = dict(BASE_CFG, ciphers="HIGH:!aNULL")
    c = build(tmp_path, cfg)
    assert c._client.tls_calls[0]["ciphers"] == "HIGH:!aNULL"


def test_disabled_switch_skips_tls_even_on_tls_port(tmp_path, fake_mqtt):
    c = build(tmp_path, dict(BASE_CFG, enabled=False))
    assert c._client.tls_calls == []
    assert c.tls_status()["enabled"] is False
    assert c.tls_status()["active"] is False


def test_unknown_version_falls_back_to_paho_default(tmp_path, fake_mqtt):
    c = build(tmp_path, dict(BASE_CFG, tls_version="TLSv9"))
    assert "tls_version" not in c._client.tls_calls[0]


def test_missing_config_file_is_tolerated(tmp_path, fake_mqtt):
    c = DJICloudConnector(
        mode="cloud", broker_port=8883,
        tls_config_path=str(tmp_path / "absent.json"),
    )
    c.connect()
    assert c._client.tls_calls == [{}]
    assert c.tls_status()["active"] is True


def test_mock_mode_never_configures_tls():
    c = DJICloudConnector(mode="mock", broker_port=8883)
    c.connect()
    assert c._client is None
    assert c.tls_status()["active"] is False


def test_status_endpoint_exposes_tls(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("AUTH_OPTIONAL", "true")
    from app.config import settings
    monkeypatch.setattr(settings, "auth_optional", True)

    old = getattr(app.state, "dji_connector", None)
    app.state.dji_connector = DJICloudConnector(mode="mock")
    try:
        r = TestClient(app).get("/api/v1/dji/status")
        assert r.status_code == 200
        tls = r.json()["tls"]
        assert tls["active"] is False
        assert 8883 in tls["ports"]
    finally:
        if old is None:
            del app.state.dji_connector
        else:
            app.state.dji_connector = old
