"""E2.3 · Copilot 长期记忆测试."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.copilot_memory import CopilotMemory
from app.models.user import User
from app.services import copilot_memory as svc
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid = uuid4()
    org = uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"m+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid, org


async def _S():
    return async_sessionmaker(engine, expire_on_commit=False)


# ============ Service layer ============

async def test_create_and_search(client) -> None:
    _, uid, org = await _mkuser()
    S = await _S()
    async with S() as s:
        await svc.create_memory(
            s, org_id=org, user_id=uid,
            kind="preference",
            content="巡检默认时长 40 分钟，偏好使用 Mavic 3E",
            tags=["巡检"], weight=70,
        )
        await svc.create_memory(
            s, org_id=org, user_id=uid,
            kind="fact",
            content="辖区包含 3 个禁飞区（NFZ）",
        )
    async with S() as s:
        hits = await svc.search_memory(
            s, org_id=org, user_id=uid, query="巡检", top_k=5,
        )
    assert len(hits) >= 1
    assert "巡检" in hits[0].memory.content
    assert hits[0].score > 50


async def test_key_upsert_dedupes(client) -> None:
    _, uid, org = await _mkuser()
    S = await _S()
    async with S() as s:
        m1 = await svc.create_memory(
            s, org_id=org, user_id=uid, kind="preference",
            content="v1", key="default_mission_duration",
        )
        m2 = await svc.create_memory(
            s, org_id=org, user_id=uid, kind="preference",
            content="v2 updated", key="default_mission_duration",
        )
    assert m1.id == m2.id
    assert m2.content == "v2 updated"


async def test_kind_validation(client) -> None:
    _, uid, org = await _mkuser()
    S = await _S()
    async with S() as s:
        with pytest.raises(ValueError):
            await svc.create_memory(
                s, org_id=org, user_id=uid, kind="bogus", content="x",
            )
        with pytest.raises(ValueError):
            await svc.create_memory(
                s, org_id=org, user_id=uid, kind="preference", content="x",
                scope="cluster",
            )


async def test_scope_org_visible_to_other_user_same_org(client) -> None:
    _, uid_a, org = await _mkuser()
    # Fabricate a second user in the same org
    uid_b = uuid4()
    tok_b = create_access_token(user_id=uid_b, org_id=org, role="user")
    S = await _S()
    async with S() as s:
        s.add(User(
            id=uid_b, email=f"b+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()

    async with S() as s:
        await svc.create_memory(
            s, org_id=org, user_id=None,
            kind="fact", content="辖区 NFZ 列表 alpha", scope="org",
        )
        await svc.create_memory(
            s, org_id=org, user_id=uid_a,
            kind="preference", content="a 的私密偏好", scope="user",
        )
    # user B searches — should see org fact, not user A private preference
    async with S() as s:
        hits = await svc.search_memory(
            s, org_id=org, user_id=uid_b, query="", top_k=10,
        )
    contents = [h.memory.content for h in hits]
    assert any("alpha" in c for c in contents)
    assert not any("私密偏好" in c for c in contents)
    del tok_b  # silence lint


async def test_org_isolation(client) -> None:
    _, uid_a, org_a = await _mkuser()
    _, uid_b, org_b = await _mkuser()
    S = await _S()
    async with S() as s:
        await svc.create_memory(
            s, org_id=org_a, user_id=uid_a,
            kind="fact", content="a-only",
        )
    async with S() as s:
        hits = await svc.search_memory(
            s, org_id=org_b, user_id=uid_b, query="", top_k=10,
        )
    assert not any("a-only" in h.memory.content for h in hits)


async def test_touch_bumps_hit_count(client) -> None:
    _, uid, org = await _mkuser()
    S = await _S()
    async with S() as s:
        m = await svc.create_memory(
            s, org_id=org, user_id=uid, kind="preference", content="hi",
        )
    async with S() as s:
        await svc.touch(s, memory_ids=[m.id])
        await svc.touch(s, memory_ids=[m.id])
    async with S() as s:
        hits = await svc.search_memory(
            s, org_id=org, user_id=uid, query="", top_k=1,
        )
    assert hits[0].memory.hit_count == 2
    assert hits[0].memory.last_hit_at is not None


async def test_purge_expired(client) -> None:
    _, uid, org = await _mkuser()
    S = await _S()
    async with S() as s:
        m = await svc.create_memory(
            s, org_id=org, user_id=uid, kind="fact",
            content="老记忆", ttl_days=1,
        )
        # Backdate to 2 days ago
        m.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        await s.commit()
    async with S() as s:
        deleted = await svc.purge_expired(s)
    assert deleted >= 1
    async with S() as s:
        hits = await svc.search_memory(
            s, org_id=org, user_id=uid, query="老", top_k=5,
        )
    assert not any("老记忆" in h.memory.content for h in hits)


async def test_ranking_prefers_weight_and_recency(client) -> None:
    _, uid, org = await _mkuser()
    S = await _S()
    async with S() as s:
        # Old low-weight
        old = await svc.create_memory(
            s, org_id=org, user_id=uid, kind="fact",
            content="老低权", weight=10,
        )
        old.created_at = datetime.now(timezone.utc) - timedelta(days=180)
        await s.commit()
        # New high-weight
        await svc.create_memory(
            s, org_id=org, user_id=uid, kind="fact",
            content="新高权", weight=80,
        )
    async with S() as s:
        hits = await svc.search_memory(
            s, org_id=org, user_id=uid, query="", top_k=5,
        )
    assert hits[0].memory.content == "新高权"


async def test_tag_filter_and_boost(client) -> None:
    _, uid, org = await _mkuser()
    S = await _S()
    async with S() as s:
        await svc.create_memory(
            s, org_id=org, user_id=uid, kind="fact",
            content="A", tags=["巡检", "MRO"],
        )
        await svc.create_memory(
            s, org_id=org, user_id=uid, kind="fact",
            content="B", tags=["测绘"],
        )
    async with S() as s:
        hits = await svc.search_memory(
            s, org_id=org, user_id=uid, tags=["巡检"], top_k=5,
        )
    contents = {h.memory.content for h in hits}
    assert "A" in contents
    assert "B" not in contents


async def test_consolidate_from_trace_creates_task_history(client) -> None:
    _, uid, org = await _mkuser()
    trace_id = uuid4()
    S = await _S()
    async with S() as s:
        m = await svc.consolidate_from_trace(
            s, org_id=org, user_id=uid, trace_id=trace_id,
            prompt="调度 UAV-42 前往北桥巡检",
            intent="dispatch_mission",
            output_text="任务 mission_id=abc 已创建",
            status="completed",
        )
    assert m is not None
    assert m.kind == "task_history"
    assert m.source_trace_id == trace_id
    assert m.ttl_days == 90
    assert "dispatch_mission" in m.content


async def test_consolidate_from_trace_skips_junk(client) -> None:
    _, uid, org = await _mkuser()
    S = await _S()
    async with S() as s:
        m1 = await svc.consolidate_from_trace(
            s, org_id=org, user_id=uid, trace_id=uuid4(),
            prompt="", intent="dispatch_mission",
        )
        m2 = await svc.consolidate_from_trace(
            s, org_id=org, user_id=uid, trace_id=uuid4(),
            prompt="你好", intent="chit_chat",
        )
        m3 = await svc.consolidate_from_trace(
            s, org_id=org, user_id=uid, trace_id=uuid4(),
            prompt="task", intent="dispatch_mission", status="failed",
        )
    assert m1 is None and m2 is None and m3 is None


async def test_consolidate_from_trace_dedup_by_trace_id(client) -> None:
    _, uid, org = await _mkuser()
    trace_id = uuid4()
    S = await _S()
    async with S() as s:
        m1 = await svc.consolidate_from_trace(
            s, org_id=org, user_id=uid, trace_id=trace_id,
            prompt="p1", intent="x", status="completed",
        )
        m2 = await svc.consolidate_from_trace(
            s, org_id=org, user_id=uid, trace_id=trace_id,
            prompt="p2 updated", intent="x", status="completed",
        )
    assert m1 and m2
    assert m1.id == m2.id
    assert "p2 updated" in m2.content


# ============ REST API ============

async def test_api_create_and_search(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/memory", headers=_h(tok),
        json={
            "kind": "preference",
            "content": "巡检偏好 M30T",
            "tags": ["巡检"],
            "weight": 60,
        },
    )
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert mid

    r2 = await client.get(
        "/api/v1/copilot/memory/search",
        headers=_h(tok), params={"q": "巡检"},
    )
    assert r2.status_code == 200
    hits = r2.json()
    assert len(hits) >= 1
    assert hits[0]["memory"]["kind"] == "preference"


async def test_api_stats(client) -> None:
    tok, _, _ = await _mkuser()
    for kind in ("preference", "fact", "fact"):
        await client.post(
            "/api/v1/copilot/memory", headers=_h(tok),
            json={"kind": kind, "content": f"{kind} row"},
        )
    r = await client.get("/api/v1/copilot/memory/stats", headers=_h(tok))
    assert r.status_code == 200
    body = r.json()
    assert body.get("preference", 0) >= 1
    assert body.get("fact", 0) >= 2


async def test_api_delete(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/memory", headers=_h(tok),
        json={"kind": "fact", "content": "to be deleted"},
    )
    mid = r.json()["id"]

    d = await client.delete(f"/api/v1/copilot/memory/{mid}", headers=_h(tok))
    assert d.status_code == 200
    assert d.json().get("deleted") is True

    d2 = await client.delete(f"/api/v1/copilot/memory/{mid}", headers=_h(tok))
    assert d2.status_code == 404


async def test_api_rejects_invalid_kind(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        "/api/v1/copilot/memory", headers=_h(tok),
        json={"kind": "bogus", "content": "x"},
    )
    assert r.status_code == 400


async def test_api_search_kind_filter(client) -> None:
    tok, _, _ = await _mkuser()
    await client.post(
        "/api/v1/copilot/memory", headers=_h(tok),
        json={"kind": "preference", "content": "偏好 A"},
    )
    await client.post(
        "/api/v1/copilot/memory", headers=_h(tok),
        json={"kind": "task_history", "content": "任务 B"},
    )
    r = await client.get(
        "/api/v1/copilot/memory/search",
        headers=_h(tok), params=[("kind", "task_history")],
    )
    assert r.status_code == 200
    kinds = {h["memory"]["kind"] for h in r.json()}
    assert kinds == {"task_history"}


async def test_api_org_scope_shared(client) -> None:
    tok_a, uid_a, org = await _mkuser()
    # Create second user in same org
    uid_b = uuid4()
    tok_b = create_access_token(user_id=uid_b, org_id=org, role="user")
    S = await _S()
    async with S() as s:
        s.add(User(
            id=uid_b, email=f"b+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()

    r = await client.post(
        "/api/v1/copilot/memory", headers=_h(tok_a),
        json={
            "kind": "fact",
            "content": "组织共享事实：NFZ 有 3 个",
            "scope": "org",
        },
    )
    assert r.status_code == 200

    r2 = await client.get(
        "/api/v1/copilot/memory/search",
        headers=_h(tok_b), params={"q": "NFZ"},
    )
    contents = [h["memory"]["content"] for h in r2.json()]
    assert any("NFZ" in c for c in contents)
