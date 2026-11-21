"""Tests for R21 · Key rotation & HSM abstraction."""
from __future__ import annotations

import json
import os
import time

import pytest

from app.services import sm2_signer
from app.services import hsm as hsm_svc


def _fresh_keypair():
    return sm2_signer.generate_keypair()


def _clear_env(monkeypatch):
    for k in [
        "SM2_PRIVATE_KEY_HEX",
        "SM2_PUBLIC_KEY_HEX",
        "SM2_KEY_ID",
        "SM2_KEYS_JSON",
        "SM2_RETIRED_KEY_IDS",
        "SM2_KEY_CREATED_AT",
        "SM2_KEY_LIFETIME_DAYS",
        "SM2_HSM_ENABLED",
    ]:
        monkeypatch.delenv(k, raising=False)
    sm2_signer._reset_cache()
    hsm_svc._reset_cache()


def test_key_metadata_reports_age_and_rotation_due(monkeypatch):
    _clear_env(monkeypatch)
    priv1, pub1 = _fresh_keypair()
    priv2, pub2 = _fresh_keypair()
    # v1 created 100 days ago, lifetime 90 → rotation_due
    # v2 created now, active
    old_ts = time.time() - 100 * 86400
    payload = [
        {
            "key_id": "v1",
            "private_hex": priv1,
            "public_hex": pub1,
            "created_at": old_ts,
            "active": True,
            "lifetime_days": 90,
        },
        {
            "key_id": "v2",
            "private_hex": priv2,
            "public_hex": pub2,
            "created_at": time.time(),
            "active": True,
            "lifetime_days": 90,
        },
    ]
    monkeypatch.setenv("SM2_KEYS_JSON", json.dumps(payload))
    monkeypatch.setenv("SM2_KEY_ID", "v2")  # active = newest
    sm2_signer._reset_cache()

    status = sm2_signer.rotation_status()
    assert status["active_key_id"] == "v2"
    assert status["any_rotation_due"] is True
    kids = {k["key_id"]: k for k in status["keys"]}
    assert kids["v1"]["rotation_due"] is True
    assert kids["v2"]["rotation_due"] is False
    # both usable for signing (have private) but v1 flagged
    assert kids["v1"]["has_private"] is True
    assert kids["v2"]["has_private"] is True


def test_retired_key_not_used_for_new_signs(monkeypatch):
    _clear_env(monkeypatch)
    priv1, pub1 = _fresh_keypair()
    priv2, pub2 = _fresh_keypair()
    payload = [
        {"key_id": "v1", "private_hex": priv1, "public_hex": pub1, "active": True},
        {"key_id": "v2", "private_hex": priv2, "public_hex": pub2, "active": True},
    ]
    monkeypatch.setenv("SM2_KEYS_JSON", json.dumps(payload))
    monkeypatch.setenv("SM2_RETIRED_KEY_IDS", "v1")
    monkeypatch.setenv("SM2_KEY_ID", "v1")  # try to use retired
    sm2_signer._reset_cache()

    # Should fall through to v2 since v1 is retired
    active = sm2_signer.active_key_id()
    assert active == "v2"

    sig = sm2_signer.sign_hash("rec-1", "abc123", "2026-07-13T00:00:00")
    assert sig is not None
    _sig_hex, kid = sig
    assert kid == "v2"

    # But a legacy signature under v1 must still verify (public key stays)
    # Re-sign using v1 directly via the low-level client
    from gmssl.sm2 import CryptSM2

    client = CryptSM2(private_key=priv1, public_key=pub1)
    msg = sm2_signer._canonical("rec-legacy", "hash-legacy", "2026-01-01T00:00:00")
    rnd = os.urandom(32).hex()
    legacy_sig = client.sign(msg, rnd)
    assert sm2_signer.verify(
        "rec-legacy", "hash-legacy", "2026-01-01T00:00:00", legacy_sig, "v1"
    )


def test_hsm_status_env_only_when_no_hsm(monkeypatch):
    _clear_env(monkeypatch)
    priv, pub = _fresh_keypair()
    monkeypatch.setenv("SM2_PRIVATE_KEY_HEX", priv)
    monkeypatch.setenv("SM2_PUBLIC_KEY_HEX", pub)
    monkeypatch.setenv("SM2_KEY_ID", "v1")
    sm2_signer._reset_cache()
    hsm_svc._reset_cache()

    status = hsm_svc.hsm_status()
    names = [b["name"] for b in status["backends"]]
    assert "pkcs11" in names and "env-hex" in names
    # PKCS11 must be unavailable without SM2_HSM_ENABLED
    hsm_pkcs = next(b for b in status["backends"] if b["name"] == "pkcs11")
    assert hsm_pkcs["available"] is False
    env = next(b for b in status["backends"] if b["name"] == "env-hex")
    assert env["available"] is True
    assert status["active_backend"] == "env-hex"


def test_signer_facade_uses_env_backend_when_hsm_disabled(monkeypatch):
    _clear_env(monkeypatch)
    priv, pub = _fresh_keypair()
    monkeypatch.setenv("SM2_PRIVATE_KEY_HEX", priv)
    monkeypatch.setenv("SM2_PUBLIC_KEY_HEX", pub)
    monkeypatch.setenv("SM2_KEY_ID", "v1")
    sm2_signer._reset_cache()
    hsm_svc._reset_cache()

    res = hsm_svc.sign_via_best_backend("rec-1", "hash-1", "2026-07-13T00:00:00")
    assert res is not None
    assert res.backend == "env-hex"
    assert res.key_id == "v1"
    assert hsm_svc.verify_via_any_backend(
        "rec-1", "hash-1", "2026-07-13T00:00:00", res.signature_hex, res.key_id
    )


def test_pkcs11_opt_in_falls_through_when_not_provisioned(monkeypatch):
    _clear_env(monkeypatch)
    priv, pub = _fresh_keypair()
    monkeypatch.setenv("SM2_PRIVATE_KEY_HEX", priv)
    monkeypatch.setenv("SM2_PUBLIC_KEY_HEX", pub)
    monkeypatch.setenv("SM2_KEY_ID", "v1")
    monkeypatch.setenv("SM2_HSM_ENABLED", "1")
    sm2_signer._reset_cache()
    hsm_svc._reset_cache()

    # PyKCS11 is not installed → pkcs11 stays unavailable, falls back to env.
    status = hsm_svc.hsm_status()
    active = status["active_backend"]
    assert active in ("env-hex",)  # confirm graceful degradation

    res = hsm_svc.sign_via_best_backend("rec-2", "hash-2", "2026-07-13T00:00:00")
    assert res is not None and res.backend == "env-hex"
