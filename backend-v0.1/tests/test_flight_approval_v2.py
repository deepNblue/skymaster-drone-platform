"""T7.0 — Flight approval v2.0 enhancement tests.

Covers:
* Second-approval gate (high-alt trigger + supervisor approve/reject)
* Batch submit (mix of drafts, high-risk, non-existent, wrong-status)
* E-signature attach / list, invalid sha256
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest


async def _make_user(email: str, role: str = "user", *, org_id=None):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid4()
    async with S() as s:
        s.add(User(id=uid, email=email,
                   hashed_pw=hash_password("StrongPass!"),
                   role=role, org_id=org_id))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), uid


def _h(t): return {"Authorization": f"Bearer {t}"}


async def _create_draft(client, tok, **overrides):
    base = {
        "title": "test flight",
        "purpose": "test",
        "category": "routine",
        "aircraft_reg": "N12345",
        "aircraft_model": "M300",
        "max_alt_m": 80,
        # small square polygon (~0.01 deg × 0.01 deg ≈ ~1 km × 1 km at
        # equator, but shrinks by cos(lat) — keep it tiny for low-risk).
        "area_polygon": [
            [104.06, 30.67], [104.063, 30.67],
            [104.063, 30.673], [104.06, 30.673],
        ],
        "start_ts": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "end_ts": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
    }
    base.update(overrides)
    r = await client.post("/api/v1/approvals", json=base, headers=_h(tok))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_second_approval_high_alt_trigger(client):
    op_tok, _ = await _make_user("op@x.com")
    sup_tok, _ = await _make_user("sup@x.com", role="supervisor")

    # max_alt_m > 120 → high-risk
    d = await _create_draft(client, op_tok, max_alt_m=180)

    r = await client.post(
        f"/api/v1/approvals/{d['id']}/submit", headers=_h(op_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending_second_approval"
    assert body["requires_second_approval"] is True
    # No authorities fanned out yet.
    assert body["authorities"] == []

    # Regular user cannot second-approve.
    r = await client.post(
        f"/api/v1/approvals/{d['id']}/second-approval",
        json={"decision": "approve"},
        headers=_h(op_tok),
    )
    assert r.status_code == 403

    # Supervisor approves → fan-out happens.
    r = await client.post(
        f"/api/v1/approvals/{d['id']}/second-approval?aircraft_weight_kg=6",
        json={"decision": "approve", "note": "double-checked"},
        headers=_h(sup_tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "in_review"
    assert body["second_approver_id"] is not None
    assert len(body["authorities"]) >= 1


@pytest.mark.asyncio
async def test_second_approval_reject_returns_to_draft(client):
    op_tok, _ = await _make_user("op2@x.com")
    sup_tok, _ = await _make_user("sup2@x.com", role="supervisor")

    d = await _create_draft(client, op_tok, category="special")
    r = await client.post(
        f"/api/v1/approvals/{d['id']}/submit", headers=_h(op_tok),
    )
    assert r.json()["status"] == "pending_second_approval"

    r = await client.post(
        f"/api/v1/approvals/{d['id']}/second-approval",
        json={"decision": "reject", "note": "insurance missing"},
        headers=_h(sup_tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft"
    assert body["requires_second_approval"] is False


@pytest.mark.asyncio
async def test_batch_submit_mixed(client):
    op_tok, _ = await _make_user("op3@x.com")

    low = await _create_draft(client, op_tok, title="low1")
    hi = await _create_draft(client, op_tok, title="hi1", max_alt_m=200)
    # Third one — already submitted.
    already = await _create_draft(client, op_tok, title="already")
    await client.post(
        f"/api/v1/approvals/{already['id']}/submit", headers=_h(op_tok),
    )

    r = await client.post(
        "/api/v1/approvals/batch-submit",
        json={
            "approval_ids": [
                low["id"], hi["id"], already["id"], str(uuid4()),
            ],
            "aircraft_weight_kg": 6,
        },
        headers=_h(op_tok),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submitted"] == 1
    assert body["held_for_second_approval"] == 1
    assert body["failed"] == 2   # already-submitted + missing UUID
    by_id = {res["approval_id"]: res for res in body["results"]}
    assert by_id[low["id"]]["ok"] is True
    assert by_id[low["id"]]["status"] == "in_review"
    assert by_id[hi["id"]]["status"] == "pending_second_approval"
    assert by_id[already["id"]]["ok"] is False
    assert "not draft" in by_id[already["id"]]["error"]


@pytest.mark.asyncio
async def test_signature_attach_and_list(client):
    op_tok, _ = await _make_user("sign1@x.com")
    d = await _create_draft(client, op_tok)

    payload = f"approval:{d['id']}:v1".encode()
    sha = hashlib.sha256(payload).hexdigest()

    # Bad sha (short) → 422.
    r = await client.post(
        f"/api/v1/approvals/{d['id']}/signatures",
        json={"payload_sha256": "deadbeef"},
        headers=_h(op_tok),
    )
    assert r.status_code == 422

    # Good.
    r = await client.post(
        f"/api/v1/approvals/{d['id']}/signatures",
        json={"payload_sha256": sha, "note": "operator sign-off"},
        headers=_h(op_tok),
    )
    assert r.status_code == 201, r.text
    sig = r.json()
    assert sig["payload_sha256"] == sha
    assert sig["signer_user_id"]

    # Unknown authority_code → 400.
    r = await client.post(
        f"/api/v1/approvals/{d['id']}/signatures",
        json={"payload_sha256": sha, "authority_code": "AAAA-BOGUS"},
        headers=_h(op_tok),
    )
    assert r.status_code == 400

    # List returns the one we made.
    r = await client.get(
        f"/api/v1/approvals/{d['id']}/signatures",
        headers=_h(op_tok),
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["payload_sha256"] == sha
