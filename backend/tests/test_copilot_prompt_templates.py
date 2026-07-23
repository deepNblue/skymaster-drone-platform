"""F4.2 · Copilot prompt template tests."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.auth import create_access_token, hash_password


pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkadmin() -> tuple[str, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"admin+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="admin", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="admin"), uid


async def _mkuser() -> tuple[str, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"u+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid


async def _create(
    client, tok, persona="operator",
    name="v", prompt="hi", activate=False,
):
    r = await client.post(
        "/api/v1/copilot/prompt-templates",
        headers=_h(tok),
        json={
            "persona": persona, "name": name,
            "system_prompt": prompt, "activate": activate,
        },
    )
    return r


# ================ Create + version ================

async def test_create_admin_ok(client) -> None:
    tok, _ = await _mkadmin()
    r = await _create(client, tok, prompt="v1")
    assert r.status_code == 201
    body = r.json()
    assert body["version"] == 1
    assert body["is_active"] is False


async def test_create_user_forbidden(client) -> None:
    tok, _ = await _mkuser()
    r = await _create(client, tok)
    assert r.status_code == 403


async def test_version_auto_increments_per_persona(client) -> None:
    tok, _ = await _mkadmin()
    for i in range(3):
        r = await _create(
            client, tok, persona="operator",
            prompt=f"v{i + 1}",
        )
        assert r.json()["version"] == i + 1
    # Analyst starts fresh at v1
    r = await _create(client, tok, persona="analyst")
    assert r.json()["version"] == 1


async def test_create_invalid_persona_400(client) -> None:
    tok, _ = await _mkadmin()
    r = await _create(client, tok, persona="wizard")
    assert r.status_code == 400


async def test_create_with_activate_marks_active(client) -> None:
    tok, _ = await _mkadmin()
    r = await _create(
        client, tok, prompt="live", activate=True,
    )
    assert r.json()["is_active"] is True

    r = await client.get(
        "/api/v1/copilot/prompt-templates/operator/active",
        headers=_h(tok),
    )
    assert r.json()["system_prompt"] == "live"


# ================ Activate — atomic swap ================

async def test_activate_demotes_prior_active(client) -> None:
    tok, _ = await _mkadmin()
    await _create(client, tok, prompt="v1", activate=True)
    await _create(client, tok, prompt="v2")

    r = await client.post(
        "/api/v1/copilot/prompt-templates/operator/versions/2/activate",
        headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2

    all_rows = (await client.get(
        "/api/v1/copilot/prompt-templates?persona=operator",
        headers=_h(tok),
    )).json()
    active = [x for x in all_rows if x["is_active"]]
    assert len(active) == 1  # exactly one active
    assert active[0]["version"] == 2


async def test_activate_missing_version_404(client) -> None:
    tok, _ = await _mkadmin()
    r = await client.post(
        "/api/v1/copilot/prompt-templates/operator/versions/99/activate",
        headers=_h(tok),
    )
    assert r.status_code == 404


async def test_activate_forbidden_for_user(client) -> None:
    tok_admin, _ = await _mkadmin()
    await _create(client, tok_admin)
    tok_user, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/prompt-templates/operator/versions/1/activate",
        headers=_h(tok_user),
    )
    assert r.status_code == 403


# ================ Rollback ================

async def test_rollback_from_v3_to_v2(client) -> None:
    tok, _ = await _mkadmin()
    await _create(client, tok, prompt="v1")
    await _create(client, tok, prompt="v2")
    await _create(client, tok, prompt="v3", activate=True)

    r = await client.post(
        "/api/v1/copilot/prompt-templates/operator/rollback",
        headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2


async def test_rollback_no_earlier_404(client) -> None:
    tok, _ = await _mkadmin()
    await _create(client, tok, activate=True)
    r = await client.post(
        "/api/v1/copilot/prompt-templates/operator/rollback",
        headers=_h(tok),
    )
    assert r.status_code == 404


# ================ Get / list ================

async def test_get_active_none_404(client) -> None:
    tok, _ = await _mkadmin()
    await _create(client, tok)  # inactive
    r = await client.get(
        "/api/v1/copilot/prompt-templates/operator/active",
        headers=_h(tok),
    )
    assert r.status_code == 404


async def test_list_orders_by_version_desc(client) -> None:
    tok, _ = await _mkadmin()
    for i in range(3):
        await _create(client, tok, prompt=f"v{i + 1}")
    r = await client.get(
        "/api/v1/copilot/prompt-templates?persona=operator",
        headers=_h(tok),
    )
    versions = [x["version"] for x in r.json()]
    assert versions == [3, 2, 1]


async def test_get_specific_version(client) -> None:
    tok, _ = await _mkadmin()
    await _create(client, tok, prompt="hello")
    r = await client.get(
        "/api/v1/copilot/prompt-templates/operator/versions/1",
        headers=_h(tok),
    )
    assert r.json()["system_prompt"] == "hello"


# ================ Diff ================

async def test_diff_versions_shows_changes(client) -> None:
    tok, _ = await _mkadmin()
    await _create(
        client, tok, prompt="Line A\nLine B\nLine C\n",
    )
    await _create(
        client, tok, prompt="Line A\nLine B changed\nLine C\n",
    )
    r = await client.get(
        "/api/v1/copilot/prompt-templates/operator/diff/1/2",
        headers=_h(tok),
    )
    body = r.json()
    assert body["changed"] is True
    assert "Line B changed" in body["diff"]
    assert "-Line B\n" in body["diff"] or "-Line B" in body["diff"]


async def test_diff_identical_prompts_unchanged(client) -> None:
    tok, _ = await _mkadmin()
    await _create(client, tok, prompt="same\n")
    await _create(client, tok, prompt="same\n")
    r = await client.get(
        "/api/v1/copilot/prompt-templates/operator/diff/1/2",
        headers=_h(tok),
    )
    assert r.json()["changed"] is False


async def test_diff_missing_version_400(client) -> None:
    tok, _ = await _mkadmin()
    await _create(client, tok)
    r = await client.get(
        "/api/v1/copilot/prompt-templates/operator/diff/1/99",
        headers=_h(tok),
    )
    assert r.status_code in (400, 404)
