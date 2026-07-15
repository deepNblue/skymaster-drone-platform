"""T6.18 — moderation_stats extra fields (pending_appeals + top_reasons_7d)."""
from __future__ import annotations

from uuid import uuid4
import pytest


def _h(t): return {"Authorization": f"Bearer {t}"}


async def _mkuser(email, role="user"):
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


@pytest.mark.asyncio
async def test_stats_extra_fields_present(client):
    admin, _ = await _mkuser("adm@t618.com", role="admin")
    author, _ = await _mkuser("auth@t618.com")

    # Seed a post and two reports of different reasons.
    r = await client.post(
        "/api/v1/community/posts",
        json={"title": "hi", "body": "hello"},
        headers=_h(author),
    )
    pid = r.json()["id"]
    await client.post(
        f"/api/v1/community/posts/{pid}/moderate",
        json={"action": "approve"},
        headers=_h(admin),
    )
    for reason in ["spam", "spam", "harassment"]:
        rep, _ = await _mkuser("rep@t618.com")
        r = await client.post(
            f"/api/v1/community/posts/{pid}/report",
            json={"reason": reason},
            headers=_h(rep),
        )
        assert r.status_code == 201

    r = await client.get(
        "/api/v1/community/moderation/stats",
        headers=_h(admin),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # T6.18 extras
    assert "pending_appeals" in body
    assert body["pending_appeals"] == 0
    assert "top_reasons_7d" in body
    reasons = {x["reason"]: x["count"] for x in body["top_reasons_7d"]}
    assert reasons.get("spam", 0) >= 2
    assert reasons.get("harassment", 0) >= 1
    # Ordered by count desc
    assert body["top_reasons_7d"][0]["reason"] == "spam"
