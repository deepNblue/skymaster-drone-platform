"""T4.11 — Scene progress SSE feed."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest


def _h(t): return {"Authorization": f"Bearer {t}"}


async def _mkuser(email="s@t411.com", role="user"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    uid = uuid4()
    org_id = uuid4()
    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(id=uid, email=email,
                   hashed_pw=hash_password("StrongPass!"),
                   role=role, org_id=org_id))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid, org_id


async def _mkscene(client, tok, name="s"):
    """Directly INSERT a Scene into the test DB to avoid the SQLite
    lack of gen_random_uuid() for the API path."""
    from uuid import UUID as _U, uuid4
    from app.db import engine
    from app.models.scene import Scene
    from sqlalchemy.ext.asyncio import async_sessionmaker
    # Extract user info from token to get org_id
    from app.services.auth import decode_token
    payload = decode_token(tok)
    org_id = _U(payload["org_id"]) if isinstance(payload["org_id"], str) else payload["org_id"]
    sub = _U(payload["sub"]) if isinstance(payload["sub"], str) else payload["sub"]
    S = async_sessionmaker(engine, expire_on_commit=False)
    sid = uuid4()
    async with S() as s:
        scene = Scene(
            id=sid,
            org_id=org_id,
            owner_user_id=sub,
            name=name,
            description="sse test",
            status="draft",
        )
        s.add(scene)
        await s.commit()
    return str(sid)


async def _promote_terminal(scene_id, status="ready"):
    """Directly bump the scene status to a terminal state so the SSE
    loop exits on its first tick."""
    from datetime import datetime, timezone
    from uuid import UUID as _U
    from app.db import engine
    from app.models.scene import Scene
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import update
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await s.execute(
            update(Scene).where(Scene.id == _U(scene_id)).values(
                status=status,
                n_gaussians=1234,
                psnr_train=27.5,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await s.commit()


def _parse_sse_events(text: str) -> list[dict]:
    """Split an SSE stream body into { event, data } records.
    ': keepalive' comments and empty lines are ignored."""
    events = []
    cur_event = "message"
    cur_data: list[str] = []
    for line in text.split("\n"):
        if line.startswith(":"):
            continue
        if line == "":
            if cur_data:
                events.append({"event": cur_event, "data": "\n".join(cur_data)})
                cur_event = "message"
                cur_data = []
            continue
        if line.startswith("event:"):
            cur_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            cur_data.append(line[len("data:"):].strip())
    return events


@pytest.mark.asyncio
async def test_scene_progress_sse_terminal_status_closes(client):
    """A scene already in a terminal state should emit one data
    frame, then an event:done frame, and end promptly (well under
    the 30-min ceiling)."""
    tok, _, _ = await _mkuser("term@t411.com")
    sid = await _mkscene(client, tok, "term-scene")
    await _promote_terminal(sid, status="ready")

    # httpx AsyncClient with .get() consumes StreamingResponse fully.
    r = await asyncio.wait_for(
        client.get(f"/api/v1/scenes/{sid}/progress.sse", headers=_h(tok)),
        timeout=5.0,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(r.text)

    # Should contain at least one message data + one 'done' terminator.
    data_evts = [e for e in events if e["event"] == "message"]
    done_evts = [e for e in events if e["event"] == "done"]
    assert data_evts, r.text
    assert done_evts, r.text

    payload = json.loads(data_evts[0]["data"])
    assert payload["scene_id"] == sid
    assert payload["status"] == "ready"
    assert payload["n_gaussians"] == 1234
    assert payload["psnr_train"] == 27.5


@pytest.mark.asyncio
async def test_scene_progress_sse_requires_auth(client):
    tok, _, _ = await _mkuser("auth-a@t411.com")
    sid = await _mkscene(client, tok, "auth")

    # No token → 401/403
    r = await client.get(f"/api/v1/scenes/{sid}/progress.sse")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_scene_progress_sse_cross_org_denied(client):
    tok_a, _, _ = await _mkuser("xa@t411.com")
    tok_b, _, _ = await _mkuser("xb@t411.com")
    sid = await _mkscene(client, tok_a, "cross-org")
    await _promote_terminal(sid, status="ready")

    # Another tenant's user should not read the scene at all.
    r = await asyncio.wait_for(
        client.get(f"/api/v1/scenes/{sid}/progress.sse", headers=_h(tok_b)),
        timeout=3.0,
    )
    assert r.status_code == 403
