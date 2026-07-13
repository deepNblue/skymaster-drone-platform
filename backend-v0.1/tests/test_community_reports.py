"""T6.5 — Community report flow tests."""
from __future__ import annotations

from uuid import uuid4

import pytest


async def _make_user(client, email: str, role: str = "user"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    uid = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=None, role=role)
    return tok, str(uid)


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


async def _create_post(client, tok: str, title="hello", body="a nice sunset flight"):
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": title, "body": body},
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_report_end_to_end(client):
    admin_tok, _ = await _make_user(client, "rep_admin@x.com", role="admin")
    author_tok, _ = await _make_user(client, "rep_author@x.com")
    reporter_tok, _ = await _make_user(client, "rep_reporter@x.com")

    post = await _create_post(client, author_tok, title="topic to report")

    # Author cannot self-report.
    r = await client.post(
        f"/api/v1/community/posts/{post['id']}/report",
        json={"reason": "spam"},
        headers=_h(author_tok),
    )
    assert r.status_code == 400

    # First report — 201.
    r = await client.post(
        f"/api/v1/community/posts/{post['id']}/report",
        json={"reason": "harassment", "note": "personal attack"},
        headers=_h(reporter_tok),
    )
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["status"] == "open"
    assert report["reason"] == "harassment"

    # Duplicate report by same reporter — 409.
    r = await client.post(
        f"/api/v1/community/posts/{post['id']}/report",
        json={"reason": "spam"},
        headers=_h(reporter_tok),
    )
    assert r.status_code == 409

    # Non-admin cannot see the queue.
    r = await client.get(
        "/api/v1/community/moderation/reports",
        headers=_h(reporter_tok),
    )
    assert r.status_code == 403

    # Admin sees the report in the open queue.
    r = await client.get(
        "/api/v1/community/moderation/reports",
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(x["id"] == report["id"] for x in items)

    # Admin resolves.
    r = await client.post(
        f"/api/v1/community/moderation/reports/{report['id']}/resolve",
        json={"action": "resolve", "note": "confirmed, post archived"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "resolved"
    assert body["resolved_by"] is not None
    assert "confirmed" in (body["note"] or "")

    # Cannot resolve twice.
    r = await client.post(
        f"/api/v1/community/moderation/reports/{report['id']}/resolve",
        json={"action": "dismiss"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 409

    # Queue is now empty for the default (open) filter.
    r = await client.get(
        "/api/v1/community/moderation/reports",
        headers=_h(admin_tok),
    )
    ids = [x["id"] for x in r.json()["items"]]
    assert report["id"] not in ids


@pytest.mark.asyncio
async def test_report_dismiss(client):
    admin_tok, _ = await _make_user(client, "rep_adm2@x.com", role="admin")
    author_tok, _ = await _make_user(client, "rep_auth2@x.com")
    reporter_tok, _ = await _make_user(client, "rep_rep2@x.com")

    post = await _create_post(client, author_tok, title="benign post")

    r = await client.post(
        f"/api/v1/community/posts/{post['id']}/report",
        json={"reason": "off_topic"},
        headers=_h(reporter_tok),
    )
    rid = r.json()["id"]

    r = await client.post(
        f"/api/v1/community/moderation/reports/{rid}/resolve",
        json={"action": "dismiss"},
        headers=_h(admin_tok),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"


@pytest.mark.asyncio
async def test_report_bad_post_404(client):
    tok, _ = await _make_user(client, "rep_404@x.com")
    r = await client.post(
        f"/api/v1/community/posts/{uuid4()}/report",
        json={"reason": "spam"},
        headers=_h(tok),
    )
    assert r.status_code == 404
