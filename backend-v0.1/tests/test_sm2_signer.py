"""Tests for R21 Step F — SM2 non-repudiation signatures."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    from app.services import rate_limit
    rate_limit.reset_bucket()
    yield
    rate_limit.reset_bucket()


# ---------------------------------------------------------------------------
# Pure signer tests
# ---------------------------------------------------------------------------


def _configure_sm2(monkeypatch):
    from app.services import sm2_signer as _sm2
    priv, pub = _sm2.generate_keypair()
    monkeypatch.setenv("SM2_PRIVATE_KEY_HEX", priv)
    monkeypatch.setenv("SM2_PUBLIC_KEY_HEX", pub)
    monkeypatch.setenv("SM2_KEY_ID", "v1")
    _sm2._reset_cache()
    return priv, pub


def test_disabled_when_no_key(monkeypatch):
    from app.services import sm2_signer as _sm2
    monkeypatch.delenv("SM2_PRIVATE_KEY_HEX", raising=False)
    monkeypatch.delenv("SM2_PUBLIC_KEY_HEX", raising=False)
    monkeypatch.delenv("SM2_KEY_ID", raising=False)
    monkeypatch.delenv("SM2_KEYS_JSON", raising=False)
    _sm2._reset_cache()
    assert _sm2.is_enabled() is False
    assert _sm2.active_key_id() is None
    # sign_hash returns None gracefully.
    assert _sm2.sign_hash("r", "h", "t") is None


def test_generate_keypair_shape():
    from app.services.sm2_signer import generate_keypair
    priv, pub = generate_keypair()
    assert len(priv) == 64
    assert len(pub) == 128
    # hex sanity
    int(priv, 16); int(pub, 16)


def test_sign_and_verify_roundtrip(monkeypatch):
    _configure_sm2(monkeypatch)
    from app.services.sm2_signer import sign_hash, verify

    signed = sign_hash("record-1", "d" * 64, "2026-07-10T15:00:00+00:00")
    assert signed is not None
    sig, kid = signed
    assert kid == "v1"
    assert len(sig) >= 100  # SM2 sigs are ~128 hex chars

    assert verify("record-1", "d" * 64, "2026-07-10T15:00:00+00:00", sig, kid) is True
    # Any tamper breaks it.
    assert verify("record-2", "d" * 64, "2026-07-10T15:00:00+00:00", sig, kid) is False
    assert verify("record-1", "e" * 64, "2026-07-10T15:00:00+00:00", sig, kid) is False
    assert verify("record-1", "d" * 64, "2026-07-10T15:01:00+00:00", sig, kid) is False


def test_verify_with_unknown_key_returns_false(monkeypatch):
    _configure_sm2(monkeypatch)
    from app.services.sm2_signer import sign_hash, verify
    sig, kid = sign_hash("r", "h" * 32, "t")  # type: ignore[misc]
    assert verify("r", "h" * 32, "t", sig, "nonexistent") is False


def test_extra_keys_json_registers_additional_keys(monkeypatch):
    from app.services import sm2_signer as _sm2
    priv1, pub1 = _sm2.generate_keypair()
    priv2, pub2 = _sm2.generate_keypair()
    monkeypatch.setenv("SM2_PRIVATE_KEY_HEX", priv1)
    monkeypatch.setenv("SM2_PUBLIC_KEY_HEX", pub1)
    monkeypatch.setenv("SM2_KEY_ID", "v1")
    monkeypatch.setenv(
        "SM2_KEYS_JSON",
        '[{"key_id":"v2","public_hex":"' + pub2 + '","private_hex":"' + priv2 + '"}]',
    )
    _sm2._reset_cache()

    ids = _sm2.known_key_ids()
    assert "v1" in ids and "v2" in ids

    sig1, kid1 = _sm2.sign_hash("r", "h", "t")  # type: ignore[misc]
    assert kid1 == "v1"
    # Message signed under v1 must NOT verify under v2's public key.
    assert _sm2.verify("r", "h", "t", sig1, "v2") is False
    # But does verify under v1.
    assert _sm2.verify("r", "h", "t", sig1, "v1") is True


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


async def _make_user(client, email: str, role: str = "admin") -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=uuid4(), email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role,
        ))
        await s.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassW0rd#"},
    )
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_status_shows_enabled(client, monkeypatch):
    _configure_sm2(monkeypatch)
    tok = await _make_user(client, "sm2_stat@x.com")
    r = await client.get(
        "/api/v1/crypto/sm2/status",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["active_key_id"] == "v1"
    assert "v1" in body["known_key_ids"]


@pytest.mark.asyncio
async def test_public_key_export(client, monkeypatch):
    priv, pub = _configure_sm2(monkeypatch)
    tok = await _make_user(client, "sm2_pub@x.com")
    r = await client.get(
        "/api/v1/crypto/sm2/public/v1",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["public_hex"] == pub
    # Unknown key → 404
    r = await client.get(
        "/api/v1/crypto/sm2/public/nope",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_verify_endpoint_roundtrip(client, monkeypatch):
    _configure_sm2(monkeypatch)
    from app.services.sm2_signer import sign_hash
    sig, kid = sign_hash("rec-x", "h" * 64, "2026-07-10T15:00:00+00:00")  # type: ignore[misc]

    tok = await _make_user(client, "sm2_ver@x.com")
    r = await client.post(
        "/api/v1/crypto/sm2/verify",
        json={
            "record_id": "rec-x", "curr_hash": "h" * 64,
            "ts": "2026-07-10T15:00:00+00:00",
            "signature_hex": sig, "key_id": kid,
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["known_key"] is True

    # Tamper.
    r = await client.post(
        "/api/v1/crypto/sm2/verify",
        json={
            "record_id": "rec-x", "curr_hash": "z" * 64,
            "ts": "2026-07-10T15:00:00+00:00",
            "signature_hex": sig, "key_id": kid,
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


@pytest.mark.asyncio
async def test_generate_keypair_requires_admin(client, monkeypatch):
    tok_op = await _make_user(client, "sm2_gen_op@x.com", role="operator")
    r = await client.post(
        "/api/v1/crypto/sm2/generate-keypair",
        headers={"Authorization": f"Bearer {tok_op}"},
    )
    assert r.status_code == 403

    tok_ad = await _make_user(client, "sm2_gen_ad@x.com", role="admin")
    r = await client.post(
        "/api/v1/crypto/sm2/generate-keypair",
        headers={"Authorization": f"Bearer {tok_ad}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["private_hex"]) == 64
    assert len(body["public_hex"]) == 128
