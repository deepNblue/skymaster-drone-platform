"""T11.2 · Community playbook API tests — end-to-end coverage.

Golden path: submit → list (own pending) → moderate → list (public) →
install → author sees install_count++ → author delete.

Also covers the boring-but-important error paths: bad DSL, bad slug,
non-admin moderator, cross-org visibility, non-approved install.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.asyncio


VALID_DSL = (
    'version: "0.1"\n'
    'name: my-playbook\n'
    'steps:\n'
    '  - id: a\n'
    '    tool: list_drones\n'
    '    args: {}\n'
)


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(role: str = "user") -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"cp+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=org, role=role)
    return tok, uid, org


async def test_submit_then_moderate_then_install(client) -> None:
    tok_author, uid_a, org_a = await _mkuser()
    tok_admin, uid_m, _ = await _mkuser(role="admin")
    tok_other, _, _ = await _mkuser()

    # 1. author submits — starts pending
    r = await client.post(
        "/api/v1/community-playbooks",
        headers=_h(tok_author),
        json={
            "slug": "landslide-scan",
            "name": "山体滑坡快查",
            "description": "阿坝州应急队常用",
            "dsl_yaml": VALID_DSL,
            "sample_inputs": {"region": "aba"},
            "tags": ["emergency", "sichuan"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    slug = body["slug"]
    assert slug == "user-landslide-scan"  # auto-prefixed
    assert body["status"] == "pending"

    # 2. public list — pending is NOT visible
    r = await client.get(
        "/api/v1/community-playbooks", headers=_h(tok_other),
    )
    assert r.status_code == 200
    assert all(p["slug"] != slug for p in r.json())

    # 3. author with include_own — visible
    r = await client.get(
        "/api/v1/community-playbooks?include_own=true",
        headers=_h(tok_author),
    )
    slugs = [p["slug"] for p in r.json()]
    assert slug in slugs

    # 4. non-admin moderation — 403
    r = await client.post(
        f"/api/v1/community-playbooks/{slug}/moderate",
        headers=_h(tok_other),
        json={"approve": True},
    )
    assert r.status_code == 403

    # 5. admin approves
    r = await client.post(
        f"/api/v1/community-playbooks/{slug}/moderate",
        headers=_h(tok_admin),
        json={"approve": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # 6. now anyone can see it
    r = await client.get(
        "/api/v1/community-playbooks", headers=_h(tok_other),
    )
    slugs = [p["slug"] for p in r.json()]
    assert slug in slugs

    # 7. other user installs into their org — new workflow row created
    r = await client.post(
        f"/api/v1/community-playbooks/{slug}/install",
        headers=_h(tok_other),
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["workflow_name"] == "山体滑坡快查"
    assert UUID(payload["workflow_id"])  # valid UUID

    # 8. install_count bumped
    r = await client.get(
        f"/api/v1/community-playbooks/{slug}", headers=_h(tok_other),
    )
    assert r.json()["install_count"] == 1

    # 9. author deletes their own submission (soft) — admin also OK
    r = await client.delete(
        f"/api/v1/community-playbooks/{slug}", headers=_h(tok_author),
    )
    assert r.status_code == 204

    # After delete → 404 on GET
    r = await client.get(
        f"/api/v1/community-playbooks/{slug}", headers=_h(tok_admin),
    )
    assert r.status_code == 404


async def test_submit_invalid_dsl_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/community-playbooks",
        headers=_h(tok),
        json={
            "slug": "bad-dsl",
            "name": "broken",
            "description": "",
            "dsl_yaml": "not: valid workflow yaml at all",
            "sample_inputs": {},
            "tags": [],
        },
    )
    assert r.status_code == 400
    assert "DSL validation failed" in r.text or "validation" in r.text.lower()


async def test_submit_bad_slug_format(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/community-playbooks",
        headers=_h(tok),
        json={
            "slug": "Not-A_Valid_Slug",
            "name": "x",
            "description": "",
            "dsl_yaml": VALID_DSL,
            "sample_inputs": {},
            "tags": [],
        },
    )
    assert r.status_code == 400
    assert "slug" in r.text.lower()


async def test_submit_duplicate_slug(client) -> None:
    tok, _, _ = await _mkuser()
    payload = {
        "slug": "dup-slug",
        "name": "n",
        "description": "",
        "dsl_yaml": VALID_DSL,
        "sample_inputs": {},
        "tags": [],
    }
    r1 = await client.post(
        "/api/v1/community-playbooks", headers=_h(tok), json=payload,
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/community-playbooks", headers=_h(tok), json=payload,
    )
    assert r2.status_code == 400
    assert "already" in r2.text.lower() or "taken" in r2.text.lower()


async def test_install_non_approved_from_another_org_rejected(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()

    # A submits (stays pending)
    r = await client.post(
        "/api/v1/community-playbooks",
        headers=_h(tok_a),
        json={
            "slug": "pending-only",
            "name": "pn",
            "description": "",
            "dsl_yaml": VALID_DSL,
            "sample_inputs": {},
            "tags": [],
        },
    )
    slug = r.json()["slug"]

    # B tries to install → 403
    r = await client.post(
        f"/api/v1/community-playbooks/{slug}/install",
        headers=_h(tok_b),
    )
    assert r.status_code == 403


async def test_reject_flow_records_reason(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_m, _, _ = await _mkuser(role="admin")

    r = await client.post(
        "/api/v1/community-playbooks",
        headers=_h(tok_a),
        json={
            "slug": "will-reject",
            "name": "wr",
            "description": "",
            "dsl_yaml": VALID_DSL,
            "sample_inputs": {},
            "tags": [],
        },
    )
    slug = r.json()["slug"]

    r = await client.post(
        f"/api/v1/community-playbooks/{slug}/moderate",
        headers=_h(tok_m),
        json={"approve": False, "reason": "涉密工具, 禁止公开"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["rejected_reason"] == "涉密工具, 禁止公开"


async def test_delete_by_other_user_forbidden(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()

    r = await client.post(
        "/api/v1/community-playbooks",
        headers=_h(tok_a),
        json={
            "slug": "not-yours",
            "name": "n", "description": "",
            "dsl_yaml": VALID_DSL,
            "sample_inputs": {}, "tags": [],
        },
    )
    slug = r.json()["slug"]

    r = await client.delete(
        f"/api/v1/community-playbooks/{slug}", headers=_h(tok_b),
    )
    assert r.status_code == 403


async def test_install_name_collision_appends_suffix(client) -> None:
    """If the caller's org already has a workflow named "my-playbook",
    the fork should be named "my-playbook (2)"."""
    tok_a, _, _ = await _mkuser()
    tok_m, _, _ = await _mkuser(role="admin")
    tok_installer, _, _ = await _mkuser()

    # Submit + approve
    r = await client.post(
        "/api/v1/community-playbooks",
        headers=_h(tok_a),
        json={
            "slug": "collision",
            "name": "shared-name",
            "description": "",
            "dsl_yaml": VALID_DSL,
            "sample_inputs": {}, "tags": [],
        },
    )
    slug = r.json()["slug"]
    await client.post(
        f"/api/v1/community-playbooks/{slug}/moderate",
        headers=_h(tok_m), json={"approve": True},
    )

    # First install
    r1 = await client.post(
        f"/api/v1/community-playbooks/{slug}/install",
        headers=_h(tok_installer),
    )
    assert r1.json()["workflow_name"] == "shared-name"

    # Second install by same user → auto-suffix
    r2 = await client.post(
        f"/api/v1/community-playbooks/{slug}/install",
        headers=_h(tok_installer),
    )
    assert r2.json()["workflow_name"] == "shared-name (2)"


async def test_get_pending_cross_org_returns_404(client) -> None:
    """A pending playbook must not leak its existence to other orgs."""
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()

    r = await client.post(
        "/api/v1/community-playbooks",
        headers=_h(tok_a),
        json={
            "slug": "leak-check",
            "name": "n", "description": "",
            "dsl_yaml": VALID_DSL,
            "sample_inputs": {}, "tags": [],
        },
    )
    slug = r.json()["slug"]

    r = await client.get(
        f"/api/v1/community-playbooks/{slug}", headers=_h(tok_b),
    )
    assert r.status_code == 404
