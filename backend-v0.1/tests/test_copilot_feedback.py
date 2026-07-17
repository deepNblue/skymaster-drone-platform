"""F4.1 · Copilot v2 turn feedback tests."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.models.vision_copilot import CopilotSessionV2, CopilotTurnV2
from app.services.auth import create_access_token, hash_password


pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser(prefix: str = "u") -> tuple[str, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"{prefix}+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid


async def _mkturn(
    *, intent: str = "takeoff", user_text: str = "起飞",
    reply_text: str = "已起飞",
) -> UUID:
    sid, tid = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(CopilotSessionV2(id=sid, title="t"))
        await s.commit()
        s.add(CopilotTurnV2(
            id=tid, session_id=sid, turn_idx=0,
            user_text=user_text, intent=intent,
            reply_text=reply_text, status="ok",
        ))
        await s.commit()
    return tid


# ================ Submit / upsert ================

async def test_submit_thumbs_up(client) -> None:
    tok, _ = await _mkuser()
    tid = await _mkturn()
    r = await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok), json={"rating": "up"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["rating"] == "up"
    assert body["updated"] is False


async def test_submit_with_comment(client) -> None:
    tok, _ = await _mkuser()
    tid = await _mkturn()
    r = await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok),
        json={"rating": "down", "comment": "解释不清楚"},
    )
    assert r.status_code == 201
    assert r.json()["comment"] == "解释不清楚"


async def test_upsert_same_user(client) -> None:
    tok, _ = await _mkuser()
    tid = await _mkturn()
    await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok), json={"rating": "up"},
    )
    r = await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok),
        json={"rating": "down", "comment": "改主意了"},
    )
    body = r.json()
    assert body["rating"] == "down"
    assert body["comment"] == "改主意了"
    assert body["updated"] is True

    stats = (await client.get(
        f"/api/v1/copilot/feedback/turns/{tid}/stats",
        headers=_h(tok),
    )).json()
    # Only one row remains after upsert
    assert stats["total"] == 1
    assert stats["down"] == 1


async def test_invalid_rating_400(client) -> None:
    tok, _ = await _mkuser()
    tid = await _mkturn()
    r = await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok), json={"rating": "meh"},
    )
    assert r.status_code == 400


async def test_missing_turn_404(client) -> None:
    tok, _ = await _mkuser()
    r = await client.post(
        f"/api/v1/copilot/feedback/turns/{uuid4()}",
        headers=_h(tok), json={"rating": "up"},
    )
    assert r.status_code == 404


async def test_comment_too_long_400(client) -> None:
    tok, _ = await _mkuser()
    tid = await _mkturn()
    r = await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok),
        json={"rating": "up", "comment": "x" * 2001},
    )
    # Pydantic Field(max_length=2000) enforces this at 422
    assert r.status_code in (400, 422)


# ================ Clear / get me ================

async def test_clear_feedback(client) -> None:
    tok, _ = await _mkuser()
    tid = await _mkturn()
    await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok), json={"rating": "up"},
    )
    r = await client.delete(
        f"/api/v1/copilot/feedback/turns/{tid}", headers=_h(tok),
    )
    assert r.status_code == 204

    r = await client.get(
        f"/api/v1/copilot/feedback/turns/{tid}/me", headers=_h(tok),
    )
    assert r.json()["rating"] is None


async def test_get_my_feedback(client) -> None:
    tok, _ = await _mkuser()
    tid = await _mkturn()
    await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok), json={"rating": "up"},
    )
    r = await client.get(
        f"/api/v1/copilot/feedback/turns/{tid}/me", headers=_h(tok),
    )
    assert r.json()["rating"] == "up"


# ================ Stats ================

async def test_turn_stats_multi_user(client) -> None:
    tid = await _mkturn()
    for i, rating in enumerate(["up", "up", "up", "down"]):
        tok, _ = await _mkuser(f"u{i}")
        await client.post(
            f"/api/v1/copilot/feedback/turns/{tid}",
            headers=_h(tok), json={"rating": rating},
        )
    tok_view, _ = await _mkuser("view")
    r = await client.get(
        f"/api/v1/copilot/feedback/turns/{tid}/stats",
        headers=_h(tok_view),
    )
    body = r.json()
    assert body["total"] == 4
    assert body["up"] == 3
    assert body["down"] == 1
    assert body["score"] == 0.5  # (3-1)/4


async def test_turn_stats_empty(client) -> None:
    tid = await _mkturn()
    tok, _ = await _mkuser()
    r = await client.get(
        f"/api/v1/copilot/feedback/turns/{tid}/stats",
        headers=_h(tok),
    )
    body = r.json()
    assert body["total"] == 0
    assert body["score"] == 0.0


# ================ Recent negative + intent scoreboard ================

async def test_recent_negative(client) -> None:
    good = await _mkturn(intent="takeoff", user_text="起飞")
    bad = await _mkturn(intent="report", user_text="生成报告",
                        reply_text="乱七八糟")

    tok1, _ = await _mkuser("a")
    tok2, _ = await _mkuser("b")
    tok3, _ = await _mkuser("c")

    await client.post(
        f"/api/v1/copilot/feedback/turns/{good}",
        headers=_h(tok1), json={"rating": "up"},
    )
    await client.post(
        f"/api/v1/copilot/feedback/turns/{bad}",
        headers=_h(tok2),
        json={"rating": "down", "comment": "太长"},
    )
    await client.post(
        f"/api/v1/copilot/feedback/turns/{bad}",
        headers=_h(tok3), json={"rating": "down"},
    )

    tok_view, _ = await _mkuser("view")
    r = await client.get(
        "/api/v1/copilot/feedback/recent-negative",
        headers=_h(tok_view),
    )
    body = r.json()
    assert len(body) == 2
    assert all(x["intent"] == "report" for x in body)

    # Filter by intent
    r = await client.get(
        "/api/v1/copilot/feedback/recent-negative?intent=takeoff",
        headers=_h(tok_view),
    )
    assert r.json() == []


async def test_intent_scoreboard(client) -> None:
    # 2 intents: 'takeoff' (3 up), 'report' (1 up, 2 down)
    takeoff_ids = [
        await _mkturn(intent="takeoff") for _ in range(3)
    ]
    report_ids = [
        await _mkturn(intent="report") for _ in range(3)
    ]
    for tid in takeoff_ids:
        tok, _ = await _mkuser()
        await client.post(
            f"/api/v1/copilot/feedback/turns/{tid}",
            headers=_h(tok), json={"rating": "up"},
        )
    ratings = ["up", "down", "down"]
    for tid, rat in zip(report_ids, ratings):
        tok, _ = await _mkuser()
        await client.post(
            f"/api/v1/copilot/feedback/turns/{tid}",
            headers=_h(tok), json={"rating": rat},
        )

    tok_view, _ = await _mkuser("view")
    r = await client.get(
        "/api/v1/copilot/feedback/intent-scoreboard?min_total=3",
        headers=_h(tok_view),
    )
    body = r.json()
    intents = [x["intent"] for x in body]
    # Worst first
    assert intents[0] == "report"
    assert intents[-1] == "takeoff"
    report_row = next(x for x in body if x["intent"] == "report")
    assert report_row["up"] == 1
    assert report_row["down"] == 2
    assert report_row["score"] == round((1 - 2) / 3, 4)


async def test_intent_scoreboard_respects_min_total(client) -> None:
    tid = await _mkturn(intent="rare")
    tok, _ = await _mkuser()
    await client.post(
        f"/api/v1/copilot/feedback/turns/{tid}",
        headers=_h(tok), json={"rating": "down"},
    )
    tok_view, _ = await _mkuser("view")
    # Only 1 feedback — below default min_total=3
    r = await client.get(
        "/api/v1/copilot/feedback/intent-scoreboard",
        headers=_h(tok_view),
    )
    intents = [x["intent"] for x in r.json()]
    assert "rare" not in intents
