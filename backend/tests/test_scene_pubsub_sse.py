"""T9.10 — Scene progress SSE pub/sub integration test.

Verifies that state transitions via `scene_pipeline.transition()` are
broadcast to active SSE subscribers in real time — NOT via DB polling.
"""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest


def _h(t):
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(email="pub@sub.test"):
    from uuid import uuid4 as _u
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    uid = _u()
    org_id = _u()
    email = email.replace("@", f"+{_u().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(
            User(
                id=uid,
                email=email,
                hashed_pw=hash_password("StrongPass!"),
                role="user",
                org_id=org_id,
            )
        )
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role="user"), uid, org_id


async def _mkscene(tok, name="pubsub"):
    from uuid import UUID as _U, uuid4 as _u
    from app.db import engine
    from app.models.scene import Scene
    from app.services.auth import decode_token
    from sqlalchemy.ext.asyncio import async_sessionmaker

    payload = decode_token(tok)
    org_id = _U(payload["org_id"]) if isinstance(payload["org_id"], str) else payload["org_id"]
    sub = _U(payload["sub"]) if isinstance(payload["sub"], str) else payload["sub"]
    S = async_sessionmaker(engine, expire_on_commit=False)
    sid = _u()
    async with S() as s:
        s.add(
            Scene(
                id=sid,
                org_id=org_id,
                owner_user_id=sub,
                name=name,
                description="pub/sub e2e",
                status="draft",
            )
        )
        await s.commit()
    return str(sid)


async def _transition_via_pipeline(scene_id, to_status):
    """Use scene_pipeline.transition() — the production code path
    that must publish to the broadcaster."""
    from datetime import datetime, timezone
    from uuid import UUID as _U
    from app.db import engine
    from app.models.scene import Scene
    from app.services.scene_pipeline import transition
    from sqlalchemy.ext.asyncio import async_sessionmaker

    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        scene = await s.get(Scene, _U(scene_id))
        await transition(s, scene, to_status)
        # Manually set updated_at (SQLite has no now() server func).
        scene.updated_at = datetime.now(timezone.utc)
        await s.commit()


def _parse_sse_events(text: str) -> list[dict]:
    events = []
    cur_event = "message"
    cur_data: list[str] = []
    for line in text.split("\n"):
        if line.startswith(":"):
            continue
        if line == "":
            if cur_data:
                events.append({"event": cur_event, "data": "\n".join(cur_data)})
                cur_event = "message"
                cur_data = []
            continue
        if line.startswith("event:"):
            cur_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            cur_data.append(line[len("data:") :].strip())
    return events


async def test_sse_receives_pubsub_transition(client):
    """
    T9.9 pub/sub 迁移的端到端验证:
      1. Client 订阅 SSE 时 scene 状态为 draft (非 terminal)
      2. 服务端通过 scene_pipeline.transition() 推进到 ready
      3. Client 应通过 broadcaster 收到 ready 状态帧, 然后 done

    如果 pub/sub 通路失败 (subscribe / publish 之一断开),
    此测试将超时失败.
    """
    tok, _, _ = await _mkuser()
    sid = await _mkscene(tok, "pubsub-e2e")

    # Kick off the SSE request in a background task.
    # httpx AsyncClient.get() consumes the streaming response fully,
    # so we schedule a transition() after a short delay to unblock it.
    trans_task: asyncio.Task | None = None

    async def _delayed_transition():
        # Wait for SSE subscription to register.
        await asyncio.sleep(0.5)
        # Walk the legal state machine to a terminal state.
        await _transition_via_pipeline(sid, "ingesting")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid, "ingested")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid, "colmap")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid, "colmap_done")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid, "training")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid, "ready")

    trans_task = asyncio.create_task(_delayed_transition())

    r = await asyncio.wait_for(
        client.get(f"/api/v1/scenes/{sid}/progress.sse", headers=_h(tok)),
        timeout=10.0,
    )
    await trans_task

    assert r.status_code == 200
    events = _parse_sse_events(r.text)
    data_evts = [e for e in events if e["event"] == "message"]
    done_evts = [e for e in events if e["event"] == "done"]

    # We should receive: initial (draft) + 4 transitions + done
    assert done_evts, r.text
    assert len(data_evts) >= 2, (
        f"Expected initial + at least one pub/sub frame, got "
        f"{len(data_evts)} data frames: {r.text!r}"
    )

    # First frame is initial snapshot (from subscribe initial=), status='draft'.
    initial_payload = json.loads(data_evts[0]["data"])
    assert initial_payload["scene_id"] == sid
    assert initial_payload["status"] == "draft"

    # Last data frame before 'done' should be the terminal state 'ready'.
    final_payload = json.loads(data_evts[-1]["data"])
    assert final_payload["status"] == "ready", (
        f"Expected final status=ready, got {final_payload}"
    )

    # Verify we saw at least one intermediate non-terminal transition —
    # this can only happen if the broadcaster pub/sub path worked.
    statuses = [json.loads(e["data"])["status"] for e in data_evts]
    intermediate = [s for s in statuses if s not in ("draft", "ready")]
    assert intermediate, (
        f"No intermediate pub/sub frames seen — pub/sub path may have "
        f"failed. All statuses: {statuses}"
    )


async def test_sse_broadcaster_isolates_scenes(client):
    """
    独立 scene 事件不应互相污染:
    subscribe scene-A, transition scene-B → A 客户端不应收到 B 的帧.
    """
    tok, _, _ = await _mkuser("iso@sub.test")
    sid_a = await _mkscene(tok, "scene-a")
    sid_b = await _mkscene(tok, "scene-b")

    async def _transition_b():
        await asyncio.sleep(0.3)
        # transition B to a distinctive terminal state
        await _transition_via_pipeline(sid_b, "ingesting")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid_b, "failed")
        # Push A through the full legal state machine to ready.
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid_a, "ingesting")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid_a, "ingested")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid_a, "colmap")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid_a, "colmap_done")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid_a, "training")
        await asyncio.sleep(0.1)
        await _transition_via_pipeline(sid_a, "ready")

    task = asyncio.create_task(_transition_b())
    r = await asyncio.wait_for(
        client.get(f"/api/v1/scenes/{sid_a}/progress.sse", headers=_h(tok)),
        timeout=10.0,
    )
    await task
    assert r.status_code == 200

    events = _parse_sse_events(r.text)
    data_evts = [e for e in events if e["event"] == "message"]
    scene_ids = {json.loads(e["data"])["scene_id"] for e in data_evts}

    # Must contain only scene-A events, never scene-B.
    assert scene_ids == {sid_a}, (
        f"topic isolation broken: got scene_ids={scene_ids}, expected {{{sid_a}}}"
    )
