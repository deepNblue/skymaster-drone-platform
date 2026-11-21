"""Tests for R18 国密 gateway — SM3/SM4 primitives + admin toggle."""
from __future__ import annotations

from uuid import uuid4
import pytest


# ------------------------------------------------------------------
# Pure-math correctness (SM3 spec vector + SM4 round-trip)
# ------------------------------------------------------------------


def test_sm3_official_test_vector():
    from app.services.sm_crypto import sm3_hex
    # GB/T 32905-2016 known-answer test.
    assert sm3_hex(b"abc") == (
        "66c7f0f462eeedd9d1f2d46bdc10e4e2"
        "4167c4875cf2f7a2297da02b8f4ba8e0"
    )


def test_sm4_roundtrip():
    from app.services.sm_crypto import sm4_encrypt, sm4_decrypt
    key = bytes(range(16))
    pt = "SkyMaster 国密 SM4 round-trip test 无人机管控平台".encode() * 3
    blob = sm4_encrypt(pt, key)
    assert sm4_decrypt(blob, key) == pt


def test_sm4_key_size_validation():
    from app.services.sm_crypto import sm4_encrypt
    with pytest.raises(ValueError):
        sm4_encrypt(b"x", key=b"short")


# ------------------------------------------------------------------
# Gateway: default OFF for latency
# ------------------------------------------------------------------


def test_gateway_default_off_is_passthrough():
    from app.services.crypto_gateway import ComplianceGateway
    g = ComplianceGateway(enabled=False)
    assert not g.enabled
    assert g.mode == "off"
    # Encrypt/decrypt/chain hash are all no-ops.
    assert g.encrypt("audit_log", "secret") == "secret"
    assert g.decrypt("audit_log", "secret") == "secret"
    assert g.chain_hash(b"\x00" * 32, "x") == b"\x00" * 32


def test_gateway_hash_mode_extends_chain():
    from app.services.crypto_gateway import ComplianceGateway
    g = ComplianceGateway(enabled=True, mode="hash", protect_modules=["audit_log"])
    prev = b"\x00" * 32
    h1 = g.chain_hash(prev, "e1")
    h2 = g.chain_hash(h1, "e2")
    assert h1 != prev
    assert h2 != h1
    assert len(h1) == 32


def test_gateway_full_mode_encrypts_and_roundtrips():
    from app.services.crypto_gateway import ComplianceGateway
    g = ComplianceGateway(
        enabled=True, mode="full", protect_modules=["audit_log"],
        sm4_key_hex="00112233445566778899aabbccddeeff",
    )
    pt = "diff payload with 中文 and special chars <>&"
    ct = g.encrypt("audit_log", pt)
    assert isinstance(ct, str) and ct != pt
    assert g.decrypt("audit_log", ct) == pt


def test_gateway_module_scope_isolation():
    from app.services.crypto_gateway import ComplianceGateway
    g = ComplianceGateway(enabled=True, mode="full", protect_modules=["audit_log"])
    # audit_log is protected, telemetry is not — passthrough.
    assert g.encrypt("telemetry", "hot-loop") == "hot-loop"
    assert g.enabled_for("audit_log") is True
    assert g.enabled_for("telemetry") is False


def test_gateway_runtime_toggle():
    from app.services.crypto_gateway import ComplianceGateway
    g = ComplianceGateway(enabled=False)
    assert g.status()["mode"] == "off"
    g.apply(enabled=True, mode="hash", modules=["audit_log"])
    assert g.status()["mode"] == "hash"
    g.apply(enabled=False)
    assert g.status()["mode"] == "off"


# ------------------------------------------------------------------
# Admin API endpoints
# ------------------------------------------------------------------


async def _login_admin(client, email="gm_admin@example.com"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=uuid4(),
            email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role="admin",
        ))
        await s.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassW0rd#"},
    )
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_compliance_status_requires_admin(client):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(User(
            id=uuid4(), email="op1@x.com",
            hashed_pw=hash_password("StrongPassW0rd#"),
            role="operator",
        ))
        await s.commit()
    r = await client.post("/api/v1/auth/login", json={
        "email": "op1@x.com", "password": "StrongPassW0rd#",
    })
    tok = r.json()["access_token"]
    r = await client.get(
        "/api/v1/admin/compliance/status",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_compliance_toggle_by_admin(client):
    from app.services.crypto_gateway import gm
    prev = gm.status()
    try:
        tok = await _login_admin(client, "gm_toggle@x.com")
        r = await client.post(
            "/api/v1/admin/compliance/toggle",
            json={"enabled": True, "mode": "hash", "modules": ["audit_log"]},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["after"]["mode"] == "hash"
        assert "audit_log" in body["after"]["modules"]

        r = await client.get(
            "/api/v1/admin/compliance/status",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.json()["mode"] == "hash"
    finally:
        gm.apply(**{k: v for k, v in {
            "enabled": prev["enabled"],
            "mode": prev["mode"],
            "modules": prev["modules"],
        }.items() if k != "mode" or v})


@pytest.mark.asyncio
async def test_compliance_toggle_rejects_bad_mode(client):
    tok = await _login_admin(client, "gm_bad_mode@x.com")
    r = await client.post(
        "/api/v1/admin/compliance/toggle",
        json={"mode": "invalid"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 422
