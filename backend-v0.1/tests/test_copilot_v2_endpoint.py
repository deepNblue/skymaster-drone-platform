"""Copilot v2 SSE endpoint — smoke test at the ASGI level.

httpx ASGI transport streaming is finicky with background tasks that
write to the response after the endpoint returns; a full end-to-end
SSE test is deferred to the integration test suite (runs against a
real uvicorn). Here we just verify the route wires up and rejects
unknown sessions.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.user import User
from app.services.auth import hash_password


@pytest.mark.asyncio
async def test_copilot_v2_route_registered(client):
    """Route table exposes /api/v1/copilot/v2/sessions/{id}/messages."""
    from app.main import app
    paths = [getattr(r, "path", "") for r in app.routes]
    assert "/api/v1/copilot/v2/sessions/{session_id}/messages" in paths


@pytest.mark.asyncio
async def test_copilot_v2_rejects_unknown_session(client):
    """Bogus session_id → 404."""
    from app.db import engine
    Sess = async_sessionmaker(engine, expire_on_commit=False)
    async with Sess() as s:
        s.add(User(
            id=uuid4(), email="cv2_reject@x.com",
            hashed_pw=hash_password("StrongPassW0rd#"),
            role="operator", org_id=uuid4(),
        ))
        await s.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "cv2_reject@x.com", "password": "StrongPassW0rd#"},
    )
    tok = r.json()["access_token"]

    fake_sid = str(uuid4())
    # httpx.AsyncClient POST — SSE endpoint returns 404 before streaming starts
    r = await client.post(
        f"/api/v1/copilot/v2/sessions/{fake_sid}/messages",
        headers={"Authorization": f"Bearer {tok}"},
        json={"prompt": "hi"},
    )
    assert r.status_code == 404
