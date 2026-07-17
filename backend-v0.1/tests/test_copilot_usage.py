"""F4.3 · Copilot usage & quota tests."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.auth import create_access_token, hash_password
from app.services.copilot_usage import record_usage


pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(
    role: str = "user", org_id: UUID | None = None,
) -> tuple[str, UUID, UUID]:
    uid = uuid4()
    org = org_id or uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"{role}+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role=role, org_id=org,
        ))
        await s.commit()
    return (
        create_access_token(user_id=uid, org_id=org, role=role),
        uid, org,
    )


async def _write(
    org_id: UUID | None, *,
    model: str = "ark-code-latest",
    prompt: int = 100, completion: int = 200,
    latency_ms: int = 500, status: str = "ok",
    persona: str | None = "operator",
) -> UUID | None:
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        return await record_usage(
            s, model=model, org_id=org_id, persona=persona,
            prompt_tokens=prompt, completion_tokens=completion,
            latency_ms=latency_ms, status=status,
        )


# ================ record_usage & pricing ================

async def test_record_writes_row_and_prices(client) -> None:
    _, _, org = await _mkuser()
    rid = await _write(org, prompt=1000, completion=500)
    assert rid is not None
    # Pricing: ark-code-latest = (0.002, 0.006) per 1k
    # ⇒ 1000*0.002/1000 + 500*0.006/1000 = 0.002 + 0.003 = 0.005
    tok, _, _ = await _mkuser(org_id=org)
    r = await client.get(
        "/api/v1/copilot/usage/me/month", headers=_h(tok),
    )
    body = r.json()
    assert body["prompt_tokens"] == 1000
    assert body["completion_tokens"] == 500
    assert body["total_tokens"] == 1500
    assert abs(body["cost_units"] - 0.005) < 1e-6
    assert body["turns"] == 1
    assert body["errors"] == 0
    assert body["error_rate"] == 0.0


async def test_record_swallows_invalid(client) -> None:
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        # Negative tokens should be swallowed → returns None.
        rid = await record_usage(
            s, model="x", prompt_tokens=-1, completion_tokens=0,
        )
    assert rid is None


async def test_status_error_bumps_error_rate(client) -> None:
    _, _, org = await _mkuser()
    await _write(org, status="ok")
    await _write(org, status="error")
    await _write(org, status="timeout")
    tok, _, _ = await _mkuser(org_id=org)
    r = await client.get(
        "/api/v1/copilot/usage/me/month", headers=_h(tok),
    )
    body = r.json()
    assert body["turns"] == 3
    assert body["errors"] == 2
    assert abs(body["error_rate"] - 2 / 3) < 1e-6


# ================ Tenant isolation ================

async def test_org_isolation(client) -> None:
    _, _, orgA = await _mkuser()
    _, _, orgB = await _mkuser()
    await _write(orgA, prompt=100, completion=200)
    await _write(orgB, prompt=999, completion=888)

    tokA, _, _ = await _mkuser(org_id=orgA)
    tokB, _, _ = await _mkuser(org_id=orgB)
    rA = (await client.get(
        "/api/v1/copilot/usage/me/month", headers=_h(tokA),
    )).json()
    rB = (await client.get(
        "/api/v1/copilot/usage/me/month", headers=_h(tokB),
    )).json()
    assert rA["total_tokens"] == 300
    assert rB["total_tokens"] == 999 + 888


async def test_user_cannot_see_other_org(client) -> None:
    _, _, orgA = await _mkuser()
    _, _, orgB = await _mkuser()
    await _write(orgA, prompt=500, completion=500)
    tokB, _, _ = await _mkuser(org_id=orgB)
    # /me/month is scoped by JWT org — B sees 0
    r = await client.get(
        "/api/v1/copilot/usage/me/month", headers=_h(tokB),
    )
    assert r.json()["total_tokens"] == 0


# ================ Rollups ================

async def test_persona_rollup_sorted_by_tokens(client) -> None:
    _, _, org = await _mkuser()
    # operator: 1000 total, analyst: 4000, instructor: 100
    await _write(org, persona="operator", prompt=500, completion=500)
    await _write(org, persona="analyst", prompt=2000, completion=2000)
    await _write(org, persona="instructor", prompt=50, completion=50)

    tok, _, _ = await _mkuser(org_id=org)
    r = await client.get(
        "/api/v1/copilot/usage/me/persona", headers=_h(tok),
    )
    body = r.json()
    personas = [x["persona"] for x in body]
    assert personas[0] == "analyst"  # highest tokens
    assert personas[-1] == "instructor"


async def test_daily_rollup(client) -> None:
    _, _, org = await _mkuser()
    for _ in range(3):
        await _write(org, prompt=100, completion=100)
    tok, _, _ = await _mkuser(org_id=org)
    r = await client.get(
        "/api/v1/copilot/usage/me/daily?days=7",
        headers=_h(tok),
    )
    body = r.json()
    # All 3 rows land in the same day bucket.
    assert len(body) == 1
    assert body[0]["turns"] == 3
    assert body[0]["tokens"] == 600


# ================ Quota ================

async def test_no_quota_means_unlimited(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.get(
        "/api/v1/copilot/usage/me/quota", headers=_h(tok),
    )
    body = r.json()
    assert body["allowed"] is True
    assert body["over_budget"] is False
    assert body["budget"] == 0


async def test_set_and_check_quota_admin(client) -> None:
    _, _, org = await _mkuser()
    tok_admin, _, _ = await _mkuser(role="admin")
    r = await client.put(
        f"/api/v1/copilot/usage/orgs/{org}/quota",
        headers=_h(tok_admin),
        json={"monthly_token_budget": 10000, "hard_stop": True},
    )
    assert r.status_code == 200
    assert r.json()["monthly_token_budget"] == 10000

    # Under budget → allowed
    await _write(org, prompt=100, completion=100)
    r = await client.get(
        f"/api/v1/copilot/usage/orgs/{org}/check",
        headers=_h(tok_admin),
    )
    body = r.json()
    assert body["allowed"] is True
    assert body["used"] == 200
    assert body["remaining"] == 9800

    # Over budget with hard_stop → NOT allowed
    await _write(org, prompt=5000, completion=5000)
    r = await client.get(
        f"/api/v1/copilot/usage/orgs/{org}/check",
        headers=_h(tok_admin),
    )
    body = r.json()
    assert body["over_budget"] is True
    assert body["allowed"] is False
    assert body["ratio"] >= 1.0


async def test_quota_upsert(client) -> None:
    _, _, org = await _mkuser()
    tok_admin, _, _ = await _mkuser(role="admin")
    await client.put(
        f"/api/v1/copilot/usage/orgs/{org}/quota",
        headers=_h(tok_admin),
        json={"monthly_token_budget": 100, "hard_stop": False},
    )
    r = await client.put(
        f"/api/v1/copilot/usage/orgs/{org}/quota",
        headers=_h(tok_admin),
        json={"monthly_token_budget": 999, "hard_stop": True},
    )
    body = r.json()
    assert body["monthly_token_budget"] == 999
    assert body["hard_stop"] is True


async def test_soft_stop_allows_over_budget(client) -> None:
    _, _, org = await _mkuser()
    tok_admin, _, _ = await _mkuser(role="admin")
    await client.put(
        f"/api/v1/copilot/usage/orgs/{org}/quota",
        headers=_h(tok_admin),
        json={"monthly_token_budget": 100, "hard_stop": False},
    )
    await _write(org, prompt=200, completion=200)
    r = await client.get(
        f"/api/v1/copilot/usage/orgs/{org}/check",
        headers=_h(tok_admin),
    )
    body = r.json()
    # soft cap → over but still allowed
    assert body["over_budget"] is True
    assert body["allowed"] is True


async def test_get_quota_missing_404(client) -> None:
    tok, _, _ = await _mkuser(role="admin")
    r = await client.get(
        f"/api/v1/copilot/usage/orgs/{uuid4()}/quota",
        headers=_h(tok),
    )
    assert r.status_code == 404


async def test_admin_endpoints_reject_non_admin(client) -> None:
    tok_user, _, _ = await _mkuser(role="user")
    other_org = uuid4()
    r = await client.get(
        f"/api/v1/copilot/usage/orgs/{other_org}/month",
        headers=_h(tok_user),
    )
    assert r.status_code == 403
    r = await client.get(
        "/api/v1/copilot/usage/models", headers=_h(tok_user),
    )
    assert r.status_code == 403


async def test_models_rollup_admin(client) -> None:
    _, _, org = await _mkuser()
    await _write(org, model="ark-code-latest", prompt=100, completion=100)
    await _write(org, model="glm-5.1", prompt=200, completion=200)
    tok, _, _ = await _mkuser(role="admin")
    r = await client.get(
        "/api/v1/copilot/usage/models?days=30", headers=_h(tok),
    )
    body = r.json()
    names = [x["model"] for x in body]
    assert "ark-code-latest" in names
    assert "glm-5.1" in names
