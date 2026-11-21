"""Shared pydantic value types.

``EmailStr`` here is a lenient replacement for pydantic's built-in
``EmailStr``. pydantic v2 bundles ``email-validator``, which hard-rejects
special-use / reserved domains (``.local``, ``.test``, ``.localhost`` ...)
with no opt-out switch on 2.3.x. That breaks login for seeded development
accounts such as ``admin@test.local`` (see ``scripts/db_seed.py`` and
``scripts/e2e_smoke.sh``) — the request body fails validation with HTTP 422
before the handler ever runs, and the same type on ``UserOut`` would also
break response serialization.

This type still runs the full syntax validator for normal domains (with
deliverability/DNS checks disabled so validation never performs network
I/O), but it tolerates the special-use/reserved-domain syntax error so
internal/dev hostnames like ``*.local`` are accepted.
"""
from __future__ import annotations

from typing import Annotated

import email_validator
from pydantic import AfterValidator, WithJsonSchema

# Matched against email_validator's EmailSyntaxError message to identify the
# single class of error we deliberately relax.
_RESERVED_DOMAIN_HINT = "special-use or reserved name"


def _validate_email(value: str) -> str:
    if not isinstance(value, str):  # pragma: no cover - defensive
        raise ValueError("email must be a string")
    value = value.strip()
    try:
        result = email_validator.validate_email(
            value,
            check_deliverability=False,
            test_environment=True,
        )
        return result.normalized
    except email_validator.EmailSyntaxError as exc:
        # Only relax the hard reject for special-use / reserved TLDs; every
        # other syntax problem (missing @, illegal characters, no dot, ...)
        # must still surface.
        if _RESERVED_DOMAIN_HINT not in str(exc):
            raise ValueError(str(exc)) from exc
        local, _, domain = value.rpartition("@")
        if not local or "." not in domain:
            raise ValueError(str(exc)) from exc
        return f"{local}@{domain}".lower()


#: Email string that accepts special-use/reserved domains (e.g. ``.local``).
EmailStr = Annotated[
    str,
    AfterValidator(_validate_email),
    WithJsonSchema({"type": "string", "format": "email"}),
]
