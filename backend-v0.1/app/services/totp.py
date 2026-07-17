"""2FA / TOTP service — RFC 6238 time-based OTP for user login MFA.

Uses ``pyotp`` (installed via requirements). Wraps three primary flows:

    1. Setup:    generate_secret(email) → provisioning URI + base32 secret
    2. Verify:   verify_totp(secret, code) → bool
    3. Backup:   generate_backup_codes() → list[str] (one-time codes)

Secrets are stored per-user in ``users.totp_secret``. Backup codes are
stored server-side in a dedicated table (future); for R12 we return
codes to the user for immediate save and do not persist.
"""
from __future__ import annotations

import secrets
import string

try:
    import pyotp
except ImportError:  # pragma: no cover
    pyotp = None  # type: ignore

_ISSUER = "SkyMaster"


def _require_pyotp() -> None:
    if pyotp is None:
        raise RuntimeError(
            "pyotp not installed — add `pyotp>=2.9` to requirements to enable 2FA"
        )


def generate_secret() -> str:
    """Return a base32 secret suitable for provisioning to authenticator apps."""
    _require_pyotp()
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    """Return an otpauth:// URI that the client renders as a QR code."""
    _require_pyotp()
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=_ISSUER)


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """Return True iff ``code`` is a valid TOTP for ``secret``.

    ``valid_window=1`` accepts the previous and next 30s window, tolerating
    minor clock drift on the client device.
    """
    _require_pyotp()
    if not code or not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


def generate_backup_codes(n: int = 10) -> list[str]:
    """Return n random 10-character backup codes."""
    alphabet = string.ascii_uppercase + string.digits
    return ["-".join(
        ["".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(2)]
    ) for _ in range(n)]
