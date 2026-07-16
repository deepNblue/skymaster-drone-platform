"""T11.1 · Official Playbook seed tests.

Two axes of coverage:
  A) DSL sanity — every shipped playbook must parse + semantic-validate
     green against the default tool registry. This is the single most
     valuable regression guard: any registry churn that would break an
     official playbook fails CI immediately.
  B) API endpoints — /playbooks list + /playbooks/{slug} detail, auth
     gating, 404 on missing slug, and the "list matches count of
     PLAYBOOKS dict" invariant.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.copilot_playbooks import PLAYBOOKS, list_playbooks
from app.services.tool_registry import build_default_registry
from app.services.workflow_dsl import parse_workflow, validate_workflow

pytestmark = pytest.mark.asyncio


# ================================================================ DSL ===

def test_every_playbook_parses_and_semantic_validates() -> None:
    """Any shipped playbook that fails semantic validation would break
    the /playbooks -> Save-as flow. This test locks that invariant."""
    reg = build_default_registry()
    assert len(PLAYBOOKS) == 3, "expected 3 seed playbooks"

    for pb in list_playbooks():
        # A) parse
        doc = parse_workflow(pb.dsl_yaml)
        assert doc.name == pb.slug, f"{pb.slug}: DSL name should match slug"

        # B) semantic validate — uses only registered tools
        validate_workflow(doc, reg)


def test_playbook_slugs_are_unique() -> None:
    slugs = [pb.slug for pb in list_playbooks()]
    assert len(slugs) == len(set(slugs))


def test_playbook_dsl_yaml_is_nonempty_and_commented() -> None:
    """Comments are how new users learn the DSL — enforce their presence
    so future edits don't strip them."""
    for pb in list_playbooks():
        assert pb.dsl_yaml.strip(), f"{pb.slug}: DSL must not be empty"
        assert "#" in pb.dsl_yaml, (
            f"{pb.slug}: DSL must retain at least one teaching comment"
        )


# ================================================================ API ===

def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = uuid4()
    org_id = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"pb+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org_id,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role="user")


async def test_list_playbooks_returns_all(client) -> None:
    tok = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks", headers=_h(tok),
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == len(PLAYBOOKS)

    # Every row has the expected schema, DSL is non-trivial, and
    # sample_inputs is a dict (may be empty for read-only playbooks).
    for row in rows:
        assert set(row.keys()) >= {
            "slug", "name", "description", "dsl_yaml", "sample_inputs",
        }
        assert row["dsl_yaml"].startswith("#")
        assert isinstance(row["sample_inputs"], dict)


async def test_get_playbook_by_slug(client) -> None:
    tok = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks/morning-inspection",
        headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "morning-inspection"
    assert "list_drones" in body["dsl_yaml"]
    # Inline coordinates are baked in — no inputs required for this playbook.
    assert body["sample_inputs"] == {}
    # And the fleet step must come first (list_drones fires immediately).
    assert body["dsl_yaml"].index("list_drones") < body["dsl_yaml"].index(
        "query_weather"
    )


async def test_get_playbook_missing_returns_404(client) -> None:
    tok = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks/does-not-exist",
        headers=_h(tok),
    )
    assert r.status_code == 404


async def test_playbook_endpoints_require_auth(client) -> None:
    r = await client.get("/api/v1/copilot/workflows/playbooks")
    assert r.status_code in (401, 403)
    r2 = await client.get(
        "/api/v1/copilot/workflows/playbooks/morning-inspection",
    )
    assert r2.status_code in (401, 403)


# ==================================================== fork playbook ===

async def test_playbook_forks_cleanly_into_own_workflow(client) -> None:
    """The intended UX: user opens a playbook, hits 'Save as...', and
    the DSL round-trips into their own copilot_workflows row without
    server-side re-validation errors."""
    tok = await _mkuser()

    # Grab the playbook.
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks/compliance-patrol",
        headers=_h(tok),
    )
    pb = r.json()

    # Save it as a personal workflow.
    r2 = await client.post(
        "/api/v1/copilot/workflows",
        headers=_h(tok),
        json={
            "name": f"my-{pb['slug']}",
            "description": f"forked from {pb['slug']}",
            "dsl_yaml": pb["dsl_yaml"],
        },
    )
    assert r2.status_code == 201, r2.text
    saved = r2.json()
    assert saved["version"] == 1
    assert saved["dsl_yaml"] == pb["dsl_yaml"]
