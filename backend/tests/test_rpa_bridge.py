"""T7.1 — RPA bridge tests: dispatch, poll, HMAC callback, idempotency."""
from __future__ import annotations

import os
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


@pytest.fixture(autouse=True)
def _reset_bridge():
    from app.services.rpa_bridge import get_bridge
    get_bridge()._reset()
    yield
    get_bridge()._reset()


async def _mkapproval_with_rpa(client, op_tok, sup_tok):
    """Create an approval, submit (high-alt to trigger second-approval),
    then have supervisor approve → in_review with rpa authorities.
    """
    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": "rpa smoke",
            "purpose": "航拍",
            "category": "routine",
            "aircraft_reg": "N-RPA",
            "aircraft_model": "M300",
            "max_alt_m": 200,  # triggers second-approval
            "area_polygon": [
                [108.30, 22.70], [108.32, 22.70],
                [108.32, 22.72], [108.30, 22.72],
            ],
            "start_ts": (now + timedelta(hours=1)).isoformat(),
            "end_ts": (now + timedelta(hours=3)).isoformat(),
        },
        headers=_h(op_tok),
    )
    assert r.status_code == 201, r.text
    approval_id = r.json()["id"]

    r = await client.post(f"/api/v1/approvals/{approval_id}/submit", headers=_h(op_tok))
    assert r.status_code == 200

    r = await client.post(
        f"/api/v1/approvals/{approval_id}/second-approval?aircraft_weight_kg=6",
        json={"decision": "approve"},
        headers=_h(sup_tok),
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_rpa_dispatch_and_idempotency(client):
    op_tok, _, org = await _mkuser("op@rpa.com")
    sup_tok, _ = await _mkuser_in_org("sup@rpa.com", org, role="supervisor")

    approval = await _mkapproval_with_rpa(client, op_tok, sup_tok)
    rpa_rows = [a for a in approval["authorities"] if a["channel"] == "rpa"]
    assert rpa_rows, f"no rpa authorities; got {approval['authorities']}"
    target = rpa_rows[0]

    # First dispatch
    r = await client.post(
        f"/api/v1/approvals/{approval['id']}/rpa-dispatch",
        json={"authority_code": target["authority_code"]},
        headers=_h(op_tok),
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["driver"] in ("mock", "shenzhen_atc_eform")
    assert job["status"] == "submitted"

    # Idempotent: second call returns same job_id
    r = await client.post(
        f"/api/v1/approvals/{approval['id']}/rpa-dispatch",
        json={"authority_code": target["authority_code"]},
        headers=_h(op_tok),
    )
    assert r.status_code == 200
    assert r.json()["job_id"] == job["job_id"]

    # Wrong authority code → 404
    r = await client.post(
        f"/api/v1/approvals/{approval['id']}/rpa-dispatch",
        json={"authority_code": "unknown_authority"},
        headers=_h(op_tok),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_rpa_poll_progresses_status(client):
    op_tok, _, org = await _mkuser("op2@rpa.com")
    sup_tok, _ = await _mkuser_in_org("sup2@rpa.com", org, role="supervisor")

    approval = await _mkapproval_with_rpa(client, op_tok, sup_tok)
    target = next(a for a in approval["authorities"] if a["channel"] == "rpa")

    r = await client.post(
        f"/api/v1/approvals/{approval['id']}/rpa-dispatch",
        json={"authority_code": target["authority_code"]},
        headers=_h(op_tok),
    )
    job_id = r.json()["job_id"]

    r = await client.get(f"/api/v1/approvals/rpa-jobs/{job_id}", headers=_h(op_tok))
    assert r.status_code == 200
    # After one poll: mock or shenzhen driver both advance to 'approving'
    assert r.json()["status"] == "approving"

    # Second poll — only mock driver reaches a terminal state
    r2 = await client.get(f"/api/v1/approvals/rpa-jobs/{job_id}", headers=_h(op_tok))
    assert r2.status_code == 200
    assert r2.json()["status"] in ("approved", "rejected", "approving")


@pytest.mark.asyncio
async def test_rpa_callback_hmac_ok_and_bad(client, monkeypatch):
    from app.services.rpa_bridge import sign_body

    monkeypatch.setenv("RPA_WEBHOOK_SECRET", "test-secret")

    op_tok, _, org = await _mkuser("op3@rpa.com")
    sup_tok, _ = await _mkuser_in_org("sup3@rpa.com", org, role="supervisor")

    approval = await _mkapproval_with_rpa(client, op_tok, sup_tok)
    target = next(a for a in approval["authorities"] if a["channel"] == "rpa")

    r = await client.post(
        f"/api/v1/approvals/{approval['id']}/rpa-dispatch",
        json={"authority_code": target["authority_code"]},
        headers=_h(op_tok),
    )
    job_id = r.json()["job_id"]

    import hashlib
    import hmac
    import json as _json

    raw_body = _json.dumps(
        {
            "job_id": job_id,
            "status": "approved",
            "external_ref": "PZ-2026-4711",
            "evidence": {"portal_ticket": "T-4711"},
        },
        separators=(",", ":"),
    ).encode()
    sig = hmac.new(b"test-secret", raw_body, hashlib.sha256).hexdigest()

    # Bad signature first
    r = await client.post(
        "/api/v1/approvals/rpa-callback",
        content=raw_body,
        headers={"X-RPA-Signature": "deadbeef", "Content-Type": "application/json"},
    )
    assert r.status_code == 401

    # Correct signature
    r = await client.post(
        "/api/v1/approvals/rpa-callback",
        content=raw_body,
        headers={"X-RPA-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # Verify the authority row was updated
    r = await client.get(
        f"/api/v1/approvals/{approval['id']}", headers=_h(op_tok),
    )
    updated = next(
        a for a in r.json()["authorities"]
        if a["authority_code"] == target["authority_code"]
    )
    assert updated["status"] == "approved"
    assert updated["external_ref"] == "PZ-2026-4711"


@pytest.mark.asyncio
async def test_rpa_callback_needs_secret(client, monkeypatch):
    """If RPA_WEBHOOK_SECRET is unset the endpoint refuses (503)."""
    monkeypatch.delenv("RPA_WEBHOOK_SECRET", raising=False)
    r = await client.post(
        "/api/v1/approvals/rpa-callback",
        content=b'{"job_id":"any","status":"approved"}',
        headers={"X-RPA-Signature": "x", "Content-Type": "application/json"},
    )
    assert r.status_code == 503
