"""T7.3 — Approval certificate PDF + QR-verify endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid, org_id


async def _mkuser_in_org(email: str, org_id, role: str = "user"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    uid = uuid4()
    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(id=uid, email=email,
                   hashed_pw=hash_password("StrongPass!"),
                   role=role, org_id=org_id))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


async def _mkapproval_approved(client, op_tok, sup_tok, sha_note="cert"):
    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "cert flight",
            "purpose": "sample",
            "category": "routine",
            "aircraft_reg": "N-CERT",
            "aircraft_model": "M300",
            "max_alt_m": 200,  # triggers second-approval flow
            "area_polygon": [
                [104.0, 30.6], [104.02, 30.6],
                [104.02, 30.62], [104.0, 30.62],
            ],
            "start_ts": (now + timedelta(hours=1)).isoformat(),
            "end_ts": (now + timedelta(hours=3)).isoformat(),
        },
        headers=_h(op_tok),
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    await client.post(f"/api/v1/approvals/{aid}/submit", headers=_h(op_tok))
    r = await client.post(
        f"/api/v1/approvals/{aid}/second-approval?aircraft_weight_kg=6",
        json={"decision": "approve"},
        headers=_h(sup_tok),
    )
    assert r.status_code == 200, r.text

    # Add an e-signature so the PDF has content in the sig block
    import hashlib
    sha = hashlib.sha256(f"approval:{aid}:{sha_note}".encode()).hexdigest()
    r = await client.post(
        f"/api/v1/approvals/{aid}/signatures",
        json={"payload_sha256": sha, "note": sha_note},
        headers=_h(sup_tok),
    )
    assert r.status_code == 201
    return aid


@pytest.mark.asyncio
async def test_certificate_pdf_renders(client):
    op_tok, _, org = await _mkuser("op-cert@t73.com")
    sup_tok, _ = await _mkuser_in_org("sup-cert@t73.com", org, role="supervisor")
    aid = await _mkapproval_approved(client, op_tok, sup_tok)

    r = await client.get(
        f"/api/v1/approvals/{aid}/certificate.pdf",
        headers=_h(op_tok),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    body = r.content
    # A real PDF starts with %PDF- and is at least a few KB with our layout
    assert body[:5] == b"%PDF-", f"not a PDF: {body[:20]!r}"
    assert len(body) > 3000
    assert body.rstrip(b"\r\n\x00 ")[-5:] == b"%%EOF"


@pytest.mark.asyncio
async def test_verify_endpoint_returns_snapshot(client):
    op_tok, _, org = await _mkuser("op-vf@t73.com")
    sup_tok, _ = await _mkuser_in_org("sup-vf@t73.com", org, role="supervisor")
    aid = await _mkapproval_approved(client, op_tok, sup_tok)

    # No auth header — verify endpoint is intentionally public.
    r = await client.get(f"/api/v1/approvals/{aid}/verify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval_id"] == aid
    assert body["status"] in {"in_review", "approved", "rejected"}
    assert isinstance(body["authorities"], list)
    assert len(body["signatures"]) >= 1
    sig = body["signatures"][0]
    assert len(sig["payload_sha256"]) == 64


@pytest.mark.asyncio
async def test_verify_unknown_approval_is_404(client):
    r = await client.get(f"/api/v1/approvals/{uuid4()}/verify")
    assert r.status_code == 404
