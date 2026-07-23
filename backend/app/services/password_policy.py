"""Password policy — enforced server-side on register / password change.

Rules (v1):
  - length >= 8
  - contain at least 3 of 4: lower / upper / digit / symbol
  - not in a short common-password blacklist
"""
from __future__ import annotations

import re

_COMMON = {
    "password", "12345678", "qwerty12", "admin123", "welcome1",
    "letmein1", "abc12345", "iloveyou", "passw0rd", "administrator",
    "111111111", "123456789", "sunshine1", "monkey123",
}

_RE_LOWER = re.compile(r"[a-z]")
_RE_UPPER = re.compile(r"[A-Z]")
_RE_DIGIT = re.compile(r"[0-9]")
_RE_SYMBOL = re.compile(r"[^A-Za-z0-9]")


class PasswordPolicyError(ValueError):
    """Raised when a password fails policy checks."""


def validate_password(pw: str, *, email: str | None = None) -> None:
    """Raise ``PasswordPolicyError`` if ``pw`` fails policy.

    Returns None on success.
    """
    if not isinstance(pw, str) or len(pw) < 8:
        raise PasswordPolicyError("Password must be at least 8 characters")
    if len(pw) > 256:
        raise PasswordPolicyError("Password too long (max 256)")

    classes = sum(bool(r.search(pw)) for r in (
        _RE_LOWER, _RE_UPPER, _RE_DIGIT, _RE_SYMBOL
    ))
    if classes < 3:
        raise PasswordPolicyError(
            "Password must contain at least 3 of: lowercase, uppercase, digit, symbol"
        )

    if pw.lower() in _COMMON:
        raise PasswordPolicyError("Password is too common")

    if email:
        local = email.split("@", 1)[0].lower()
        if local and local in pw.lower():
            raise PasswordPolicyError("Password must not contain the email local-part")
