"""Schema validation smoke tests for app.schemas.auth."""
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, TokenResponse, UserOut


def test_login_request_valid() -> None:
    req = LoginRequest(email="pilot@example.com", password="hunter2")
    assert req.email == "pilot@example.com"
    assert req.password == "hunter2"


def test_login_request_rejects_bad_email() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="x")


def test_login_request_rejects_empty_password() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="pilot@example.com", password="")


def test_token_response_validates_from_dict() -> None:
    payload = {
        "access_token": "jwt.header.payload.signature",
        "token_type": "bearer",
        "expires_in": 900,
        "user": {
            "id": str(uuid4()),
            "email": "pilot@example.com",
            "role": "pilot",
            "org_id": None,
            "created_at": None,
        },
    }
    resp = TokenResponse.model_validate(payload)
    assert resp.access_token == payload["access_token"]
    assert resp.token_type == "bearer"
    assert resp.expires_in == 900
    assert isinstance(resp.user, UserOut)
    assert resp.user.email == "pilot@example.com"
    assert resp.user.role == "pilot"


def test_token_response_default_token_type() -> None:
    payload = {
        "access_token": "abc",
        "expires_in": 60,
        "user": {
            "id": str(uuid4()),
            "email": "a@b.co",
            "role": "admin",
        },
    }
    resp = TokenResponse.model_validate(payload)
    assert resp.token_type == "bearer"
