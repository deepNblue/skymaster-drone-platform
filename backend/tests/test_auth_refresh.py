"""Tests for auth JWT refresh + password change endpoints (R10).

Requires Postgres because the User model uses Postgres-specific server
defaults (gen_random_uuid). On CI without Postgres these tests skip.
"""
from __future__ import annotations

import os
import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        "postgresql" not in os.environ.get("DATABASE_URL", ""),
        reason="auth refresh tests require Postgres",
    ),
]


async def _seed_user(client, email="rr@x.com", pw="pw12345"):
    """Insert a user into the shared test DB via the app's engine.

    conftest.py has already created the SQLite tables at fixture setup.
    """
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        u = User(
            email=email, hashed_pw=hash_password(pw), role="operator",
        )
        session.add(u)
        await session.commit()


async def test_refresh_valid_token_rotates(client):
    """A valid refresh token exchanges for a new access+refresh pair."""
    await _seed_user(client, email="r1@x.com", pw="pw12345")
    r = await client.post(
        "/api/v1/auth/login", json={"email": "r1@x.com", "password": "pw12345"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    refresh = data["refresh_token"]
    assert refresh
    assert data["access_token"] != refresh

    r2 = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh}
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["access_token"]
    assert d2["refresh_token"]
    assert d2["refresh_token"] != refresh  # rotation


async def test_refresh_rejects_access_token(client):
    """Access tokens must NOT be accepted on /auth/refresh (typ check)."""
    await _seed_user(client, email="r2@x.com", pw="pw12345")
    r = await client.post(
        "/api/v1/auth/login", json={"email": "r2@x.com", "password": "pw12345"},
    )
    access = r.json()["access_token"]
    r2 = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": access}
    )
    assert r2.status_code == 401
    assert "refresh" in r2.json()["detail"].lower()


async def test_change_password_success(client):
    await _seed_user(client, email="r3@x.com", pw="oldpass1")
    r = await client.post(
        "/api/v1/auth/login", json={"email": "r3@x.com", "password": "oldpass1"},
    )
    access = r.json()["access_token"]
    r2 = await client.post(
        "/api/v1/auth/password",
        json={"old_password": "oldpass1", "new_password": "newpass2"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r2.status_code == 200, r2.text
    # Old password no longer works
    r3 = await client.post(
        "/api/v1/auth/login", json={"email": "r3@x.com", "password": "oldpass1"},
    )
    assert r3.status_code == 401
    # New password works
    r4 = await client.post(
        "/api/v1/auth/login", json={"email": "r3@x.com", "password": "newpass2"},
    )
    assert r4.status_code == 200


async def test_change_password_wrong_old(client):
    await _seed_user(client, email="r4@x.com", pw="pw12345")
    r = await client.post(
        "/api/v1/auth/login", json={"email": "r4@x.com", "password": "pw12345"},
    )
    access = r.json()["access_token"]
    r2 = await client.post(
        "/api/v1/auth/password",
        json={"old_password": "wrongpw", "new_password": "newpass2"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r2.status_code == 400
