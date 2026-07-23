"""Unit tests for TOTP service (skips gracefully if pyotp missing)."""
from __future__ import annotations

import pytest

try:
    import pyotp
except ImportError:  # pragma: no cover
    pyotp = None

pytestmark = pytest.mark.skipif(pyotp is None, reason="pyotp not installed")


def test_generate_secret_is_base32():
    from app.services.totp import generate_secret
    s = generate_secret()
    assert isinstance(s, str)
    # base32 alphabet: A-Z + 2-7
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in s)
    assert len(s) >= 16


def test_provisioning_uri_shape():
    from app.services.totp import generate_secret, provisioning_uri
    uri = provisioning_uri(generate_secret(), "alice@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=SkyMaster" in uri
    assert "alice%40example.com" in uri or "alice@example.com" in uri


def test_verify_correct_and_wrong():
    from app.services.totp import generate_secret, verify_totp
    secret = generate_secret()
    good_code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, good_code) is True
    assert verify_totp(secret, "000000") is False  # almost certainly wrong
    assert verify_totp(secret, "abc123") is False  # non-digit
    assert verify_totp(secret, "1") is False        # short


def test_backup_codes_unique_and_shape():
    from app.services.totp import generate_backup_codes
    codes = generate_backup_codes(5)
    assert len(codes) == 5
    assert len(set(codes)) == 5  # all unique
    for c in codes:
        parts = c.split("-")
        assert len(parts) == 2
        assert all(len(p) == 5 for p in parts)
