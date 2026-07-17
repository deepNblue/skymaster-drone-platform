"""T12.1 · Copilot workflow schedules — CRUD + cron semantics.

Focus:
  A) service-layer sanity (compute_next_fire correctness, invalid cron
     rejection, org isolation)
  B) API-level CRUD (create/list/patch/delete + 400/404 mapping)
  C) route ordering — /schedules must NOT be caught by /{wf_id}
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.copilot_workflow import CopilotWorkflow
from app.models.user import User
from app.services.auth import create_access_token, hash_password
from app.services.workflow_schedules import (
    ScheduleError,
    compute_next_fire,
    create_schedule,
    delete_schedule,
    list_schedules,
    update_schedule,
)

pytestmark = pytest.mark.asyncio


# =========================================================== helpers ===


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid = uuid4()
    org_id = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"sch+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org_id,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=org_id, role="user")
    return tok, uid, org_id


async def _mkworkflow(org_id: UUID, created_by: UUID) -> UUID:
    """Insert a minimal stored workflow directly, bypassing the API."""
    wf_id = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CopilotWorkflow(
            id=wf_id,
            org_id=org_id,
            owner_user_id=created_by,
            name="test-wf",
            description="",
            dsl_yaml=(
                'version: "0.1"\n'
                'name: test-wf\n'
                'steps:\n'
                '  - id: a\n'
                '    tool: list_drones\n'
                '    args: {}\n'
            ),
            version=1,
        ))
        await s.commit()
    return wf_id


# ================================================= compute_next_fire ===


def test_compute_next_fire_daily() -> None:
    base = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)
    nxt = compute_next_fire("0 9 * * *", base=base)
    assert nxt == datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


def test_compute_next_fire_weekly_monday() -> None:
    # 2026-07-15 is a Wednesday. Next Monday 09:00 UTC.
    base = datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc)
    nxt = compute_next_fire("0 9 * * MON", base=base)
    assert nxt == datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def test_compute_next_fire_naive_base_treated_as_utc() -> None:
    naive = datetime(2026, 7, 15, 8, 30)  # no tzinfo
    nxt = compute_next_fire("0 9 * * *", base=naive)
    assert nxt.tzinfo is not None  # always returns aware


def test_compute_next_fire_invalid_cron_raises() -> None:
    with pytest.raises(ScheduleError):
        compute_next_fire("not a cron")
    with pytest.raises(ScheduleError):
        compute_next_fire("* * * *")  # 4 fields (needs 5)


# =========================================================== service ===


async def test_service_create_and_list(client) -> None:
    _, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        row = await create_schedule(
            db,
            org_id=org_id,
            workflow_id=wf_id,
            cron_expr="0 9 * * *",
            inputs={"k": 1},
            created_by=uid,
        )
        assert row.next_fire_at is not None
        assert row.enabled is True

        rows = await list_schedules(db, org_id=org_id)
        assert len(rows) == 1
        assert rows[0].workflow_id == wf_id


async def test_service_create_rejects_foreign_workflow(client) -> None:
    _, uid_a, org_a = await _mkuser()
    _, _, org_b = await _mkuser()

    wf_b = await _mkworkflow(org_b, uid_a)  # workflow in *other* org

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        with pytest.raises(ScheduleError, match="workflow not found"):
            await create_schedule(
                db,
                org_id=org_a,      # user A's org
                workflow_id=wf_b,  # but workflow belongs to org B
                cron_expr="0 9 * * *",
                inputs={},
                created_by=uid_a,
            )


async def test_service_disable_clears_next_fire(client) -> None:
    _, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        row = await create_schedule(
            db, org_id=org_id, workflow_id=wf_id,
            cron_expr="0 9 * * *", inputs={}, created_by=uid,
        )
        assert row.next_fire_at is not None

        updated = await update_schedule(
            db, org_id=org_id, schedule_id=row.id, enabled=False,
        )
        assert updated.enabled is False
        # Disabled schedules leave the hot-path index.
        assert updated.next_fire_at is None


async def test_service_re_enable_recomputes_next_fire(client) -> None:
    _, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        row = await create_schedule(
            db, org_id=org_id, workflow_id=wf_id,
            cron_expr="0 9 * * *", inputs={}, created_by=uid,
            enabled=False,
        )
        assert row.next_fire_at is None

        updated = await update_schedule(
            db, org_id=org_id, schedule_id=row.id, enabled=True,
        )
        assert updated.next_fire_at is not None


async def test_service_update_invalid_cron_raises(client) -> None:
    _, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        row = await create_schedule(
            db, org_id=org_id, workflow_id=wf_id,
            cron_expr="0 9 * * *", inputs={}, created_by=uid,
        )
        with pytest.raises(ScheduleError):
            await update_schedule(
                db, org_id=org_id, schedule_id=row.id,
                cron_expr="totally invalid",
            )


async def test_service_delete_returns_bool(client) -> None:
    _, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        row = await create_schedule(
            db, org_id=org_id, workflow_id=wf_id,
            cron_expr="0 9 * * *", inputs={}, created_by=uid,
        )
        ok = await delete_schedule(
            db, org_id=org_id, schedule_id=row.id,
        )
        assert ok is True

        # second delete of same id → False
        ok2 = await delete_schedule(
            db, org_id=org_id, schedule_id=row.id,
        )
        assert ok2 is False


# =============================================================== API ===


async def test_api_create_schedule(client) -> None:
    tok, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    r = await client.post(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok),
        json={
            "workflow_id": str(wf_id),
            "cron_expr": "0 9 * * *",
            "inputs": {"foo": "bar"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["workflow_id"] == str(wf_id)
    assert body["cron_expr"] == "0 9 * * *"
    assert body["inputs"] == {"foo": "bar"}
    assert body["enabled"] is True
    assert body["next_fire_at"] is not None


async def test_api_create_schedule_invalid_cron_400(client) -> None:
    tok, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    r = await client.post(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok),
        json={
            "workflow_id": str(wf_id),
            "cron_expr": "totally invalid",
            "inputs": {},
        },
    )
    assert r.status_code == 400


async def test_api_create_schedule_foreign_workflow_400(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    _, _, org_b = await _mkuser()
    wf_b = await _mkworkflow(org_b, uid_a)

    r = await client.post(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok_a),
        json={
            "workflow_id": str(wf_b),
            "cron_expr": "0 9 * * *",
            "inputs": {},
        },
    )
    assert r.status_code == 400


async def test_api_list_schedules_scoped_to_org(client) -> None:
    tok_a, uid_a, org_a = await _mkuser()
    tok_b, uid_b, org_b = await _mkuser()

    wf_a = await _mkworkflow(org_a, uid_a)
    wf_b = await _mkworkflow(org_b, uid_b)

    # A creates a schedule.
    await client.post(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok_a),
        json={
            "workflow_id": str(wf_a),
            "cron_expr": "0 9 * * *",
            "inputs": {},
        },
    )
    # B creates one too.
    await client.post(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok_b),
        json={
            "workflow_id": str(wf_b),
            "cron_expr": "*/5 * * * *",
            "inputs": {},
        },
    )

    r_a = await client.get(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok_a),
    )
    slugs_a = [row["workflow_id"] for row in r_a.json()]
    assert slugs_a == [str(wf_a)]  # A sees only its own

    r_b = await client.get(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok_b),
    )
    slugs_b = [row["workflow_id"] for row in r_b.json()]
    assert slugs_b == [str(wf_b)]


async def test_api_patch_schedule_toggle_enabled(client) -> None:
    tok, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    r = await client.post(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok),
        json={
            "workflow_id": str(wf_id),
            "cron_expr": "0 9 * * *",
            "inputs": {},
        },
    )
    sid = r.json()["id"]

    r2 = await client.patch(
        f"/api/v1/copilot/workflows/schedules/{sid}",
        headers=_h(tok),
        json={"enabled": False},
    )
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False
    assert r2.json()["next_fire_at"] is None


async def test_api_patch_schedule_missing_404(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.patch(
        f"/api/v1/copilot/workflows/schedules/{uuid4()}",
        headers=_h(tok),
        json={"enabled": False},
    )
    assert r.status_code == 404


async def test_api_delete_schedule(client) -> None:
    tok, uid, org_id = await _mkuser()
    wf_id = await _mkworkflow(org_id, uid)

    r = await client.post(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok),
        json={
            "workflow_id": str(wf_id),
            "cron_expr": "0 9 * * *",
            "inputs": {},
        },
    )
    sid = r.json()["id"]

    r2 = await client.delete(
        f"/api/v1/copilot/workflows/schedules/{sid}",
        headers=_h(tok),
    )
    assert r2.status_code == 204

    # second delete → 404
    r3 = await client.delete(
        f"/api/v1/copilot/workflows/schedules/{sid}",
        headers=_h(tok),
    )
    assert r3.status_code == 404


async def test_schedules_route_precedes_wf_id(client) -> None:
    """The /schedules routes MUST take precedence over /{wf_id} — else
    listing schedules would 404 as an unknown workflow."""
    tok, _, _ = await _mkuser()

    r = await client.get(
        "/api/v1/copilot/workflows/schedules",
        headers=_h(tok),
    )
    # Empty org → 200 with []; NOT 404 (which would signal route
    # ordering broke and /{wf_id} caught the string "schedules").
    assert r.status_code == 200
    assert r.json() == []
