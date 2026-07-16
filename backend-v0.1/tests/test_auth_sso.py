"""Unit tests for SSO/OAuth helpers.

Full round-trip against Google/GitHub is not viable in CI — we test the
signed-state helpers, provider registration, and endpoint contracts.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1 import auth_sso


def _clear_env(monkeypatch):
    for k in (
        "OAUTH_GOOGLE_CLIENT_ID", "OAUTH_GOOGLE_CLIENT_SECRET",
        "OAUTH_GITHUB_CLIENT_ID", "OAUTH_GITHUB_CLIENT_SECRET",
    ):
        monkeypatch.delenv(k, raising=False)


def test_no_providers_configured(monkeypatch):
    _clear_env(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/v1/auth/sso/providers")
    assert r.status_code == 200
    assert r.json() == {"providers": []}


def test_google_provider_registers(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "google-id")
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    client = TestClient(app)
    r = client.get("/api/v1/auth/sso/providers")
    assert r.status_code == 200
    assert "google" in r.json()["providers"]


def test_authorize_redirects(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_ID", "gh-id")
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_SECRET", "gh-secret")
    client = TestClient(app)
    r = client.get(
        "/api/v1/auth/sso/github/authorize",
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert loc.startswith("https://github.com/login/oauth/authorize")
    assert "client_id=gh-id" in loc
    assert "state=" in loc


def test_authorize_missing_provider(monkeypatch):
    _clear_env(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/v1/auth/sso/google/authorize")
    assert r.status_code == 404


def test_state_signing_roundtrip():
    tok = auth_sso._sign_state("google", "/dashboard")
    claims = auth_sso._verify_state(tok)
    assert claims["provider"] == "google"
    assert claims["next"] == "/dashboard"
    assert "nonce" in claims


def test_state_verify_rejects_garbage():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        auth_sso._verify_state("not-a-real-token")
    assert exc.value.status_code == 400


def test_callback_bad_state(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_SECRET", "sec")
    client = TestClient(app)
    r = client.get(
        "/api/v1/auth/sso/google/callback?code=abc&state=garbage"
    )
    assert r.status_code == 400
