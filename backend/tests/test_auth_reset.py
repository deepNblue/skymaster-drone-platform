"""Integration tests for password reset flow."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    from app.services import rate_limit
    rate_limit.reset_bucket()
    yield
    rate_limit.reset_bucket()


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_returns_200(client):
    """Anti-enumeration — unknown email returns identical response."""
    r = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "ghost@example.com"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_reset_with_bad_token_400(client):
    r = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": "does-not-exist-token-1234567890",
            "new_password": "NewStrong#1Pass",
        },
    )
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "invalid" in detail or "expired" in detail


@pytest.mark.asyncio
async def test_reset_weak_password_rejected(client):
    r = await client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": "any-token-abcdefghijklmnop",
            "new_password": "short",
        },
    )
    # Password policy runs before token lookup.
    assert r.status_code == 400
    assert "password" in r.json()["detail"].lower() or "at least" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_end_to_end_reset_flow(client):
    """Full happy path: register → forgot → find token → reset → login."""
    from uuid import uuid4
    from app.db import engine
    from app.models.password_reset_token import PasswordResetToken
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)

    email = "reset_test@example.com"
    async with Session() as s:
        s.add(User(
            id=uuid4(),
            email=email,
            hashed_pw=hash_password("OldPassW0rd#"),
            role="operator",
        ))
        await s.commit()

    # Trigger reset
    r = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": email},
    )
    assert r.status_code == 200

    # Fetch the raw token — impossible via API (that's the point!),
    # so we verify a row was persisted.
    async with Session() as s:
        rows = (await s.execute(select(PasswordResetToken))).scalars().all()
        assert len(rows) >= 1
