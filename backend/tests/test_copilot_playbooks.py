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
    assert len(PLAYBOOKS) == 6, "expected 6 seed playbooks"

    for pb in list_playbooks():
        # A) parse
        doc = parse_workflow(pb.dsl_yaml)
        assert doc.name == pb.slug, f"{pb.slug}: DSL name should match slug"

        # B) semantic validate — uses only registered tools
        validate_workflow(doc, reg)


def test_playbook_slugs_are_unique() -> None:
    slugs = [pb.slug for pb in list_playbooks()]
    assert len(slugs) == len(set(slugs))


def test_playbook_catalog_covers_expected_domains() -> None:
    """Track E2.2 target: 6 seed playbooks across ops + 3 domains.
    If someone accidentally deletes one, this fails loudly rather than
    letting the UI silently lose a menu item."""
    have = {pb.slug for pb in list_playbooks()}
    assert have >= {
        "morning-inspection",     # ops
        "emergency-response",     # ops
        "compliance-patrol",      # ops
        "crop-protection",        # domain
        "line-inspection",        # domain
        "security-patrol",        # domain
    }


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
            "tags",
        }
        assert row["dsl_yaml"].startswith("#")
        assert isinstance(row["sample_inputs"], dict)
        assert isinstance(row["tags"], list)


# =========================================== T11.4: tag/search filters ===

async def test_list_playbooks_filter_by_tag(client) -> None:
    """Domain playbooks (tag='domain') should be exactly the 3 new
    ones from T11.3; ops playbooks (tag='ops') the 3 originals."""
    tok = await _mkuser()

    r_dom = await client.get(
        "/api/v1/copilot/workflows/playbooks?tag=domain",
        headers=_h(tok),
    )
    assert r_dom.status_code == 200
    domain_slugs = {row["slug"] for row in r_dom.json()}
    assert domain_slugs == {
        "crop-protection", "line-inspection", "security-patrol",
    }

    r_ops = await client.get(
        "/api/v1/copilot/workflows/playbooks?tag=ops",
        headers=_h(tok),
    )
    ops_slugs = {row["slug"] for row in r_ops.json()}
    assert ops_slugs == {
        "morning-inspection", "emergency-response", "compliance-patrol",
    }


async def test_list_playbooks_filter_by_tag_case_insensitive(client) -> None:
    tok = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks?tag=SENSITIVE",
        headers=_h(tok),
    )
    slugs = {row["slug"] for row in r.json()}
    # emergency + crop + security all carry a sensitive tool.
    assert slugs == {"emergency-response", "crop-protection", "security-patrol"}


async def test_list_playbooks_filter_by_tag_unknown_returns_empty(
    client,
) -> None:
    tok = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks?tag=nonexistent",
        headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_list_playbooks_search_query_matches_name(client) -> None:
    tok = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks?q=植保",
        headers=_h(tok),
    )
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["slug"] == "crop-protection"


async def test_list_playbooks_search_query_matches_description(client) -> None:
    tok = await _mkuser()
    # Only compliance-patrol description contains "审计".
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks?q=审计",
        headers=_h(tok),
    )
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["slug"] == "compliance-patrol"


async def test_list_playbooks_tag_and_query_compose(client) -> None:
    tok = await _mkuser()
    # domain + "巡" -> line-inspection (输电线) but NOT security-patrol
    # (夜巡 also matches — this is the more interesting case).
    r = await client.get(
        "/api/v1/copilot/workflows/playbooks?tag=domain&q=巡",
        headers=_h(tok),
    )
    slugs = {row["slug"] for row in r.json()}
    # Both line-inspection (巡线) and security-patrol (夜巡) match.
    assert slugs == {"line-inspection", "security-patrol"}


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
