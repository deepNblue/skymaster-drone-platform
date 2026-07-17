"""T6.12 — reporter reputation query endpoint."""
from __future__ import annotations

from uuid import uuid4

import pytest


def _h(t): return {"Authorization": f"Bearer {t}"}


async def _mkuser(email: str, role: str = "user"):
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
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


async def _mkpost(client, tok, title="p"):
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": title, "body": f"body-{uuid4().hex[:6]}"},
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _seed_history(client, admin_tok, reporter_tok, *, resolves, dismisses):
    author_tok, _ = await _mkuser(f"hh-{uuid4().hex[:6]}@t612.com")
    for i, action in enumerate(["resolve"] * resolves + ["dismiss"] * dismisses):
        pid = await _mkpost(client, author_tok, title=f"h-{i}")
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": "spam"},
            headers=_h(reporter_tok),
        )
        assert r.status_code == 201
        rid = r.json()["id"]
        r = await client.post(
            f"/api/v1/community/moderation/reports/{rid}/resolve",
            json={"action": action, "note": ""},
            headers=_h(admin_tok),
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_reputation_trusted(client, monkeypatch):
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "999")
    admin_tok, _ = await _mkuser("adm@t612.com", role="admin")
    rep_tok, rep_id = await _mkuser("trusted@t612.com")
    await _seed_history(client, admin_tok, rep_tok, resolves=5, dismisses=0)

    r = await client.get(
        f"/api/v1/community/moderation/reporters/{rep_id}/reputation",
        headers=_h(admin_tok),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["resolved"] == 5
    assert d["dismissed"] == 0
    assert d["open"] == 0
    assert d["weight"] == 2.0
    assert d["label"] == "trusted"


@pytest.mark.asyncio
async def test_reputation_suspect(client, monkeypatch):
    monkeypatch.setenv("COMMUNITY_REPORT_RATE_MAX", "999")
    admin_tok, _ = await _mkuser("adm2@t612.com", role="admin")
    rep_tok, rep_id = await _mkuser("suspect@t612.com")
    await _seed_history(client, admin_tok, rep_tok, resolves=0, dismisses=5)

    r = await client.get(
        f"/api/v1/community/moderation/reporters/{rep_id}/reputation",
        headers=_h(admin_tok),
    )
    d = r.json()
    assert d["resolved"] == 0
    assert d["dismissed"] == 5
    assert d["weight"] == 0.3
    assert d["label"] == "suspect"


@pytest.mark.asyncio
async def test_reputation_fresh_neutral(client):
    admin_tok, _ = await _mkuser("adm3@t612.com", role="admin")
    _, rep_id = await _mkuser("fresh@t612.com")

    r = await client.get(
        f"/api/v1/community/moderation/reporters/{rep_id}/reputation",
        headers=_h(admin_tok),
    )
    d = r.json()
    assert d["resolved"] == 0
    assert d["dismissed"] == 0
    assert d["weight"] == 1.0
    assert d["label"] == "neutral"


@pytest.mark.asyncio
async def test_reputation_admin_only(client):
    non_admin_tok, _ = await _mkuser("regular@t612.com")
    _, rep_id = await _mkuser("target@t612.com")
    r = await client.get(
        f"/api/v1/community/moderation/reporters/{rep_id}/reputation",
        headers=_h(non_admin_tok),
    )
    assert r.status_code == 403
