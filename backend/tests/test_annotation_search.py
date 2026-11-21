"""D2.4 · Annotation semantic search tests."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import engine
from app.models.user import User
from app.services.annotation_search import (
    parse_query, suggest_annotation_from_query,
)
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.asyncio


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"annsearch+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org, role="user"), uid, org


async def _mkann(client, tok: str, sid: UUID, **kv) -> dict:
    payload = {
        "geom_kind": "point",
        "geom_vertices": [[0, 0, 0]],
        "label": "缺陷点",
        "severity": "info",
        "layer": "default",
    }
    payload.update(kv)
    r = await client.post(
        f"/api/v1/scenes/{sid}/annotations",
        headers=_h(tok), json=payload,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- Pure-function unit tests --------------------------------------

def test_parse_query_extracts_semantic_hints() -> None:
    p = parse_query("找出所有裂缝, 尤其是紧急的")
    assert "line" in p["geom_kinds"]  # 裂缝 -> line
    assert "critical" in p["severities"]  # 紧急 -> critical


def test_parse_query_layer_alias() -> None:
    p = parse_query("看看缺陷层的问题")
    assert "defect" in p["layers"]


def test_parse_query_polygon_area() -> None:
    p = parse_query("圈出淤积区")
    assert "polygon" in p["geom_kinds"]


def test_parse_query_empty() -> None:
    p = parse_query("")
    assert p["raw"] == ""
    assert p["keywords"] == []
    assert not p["geom_kinds"]


def test_suggest_returns_none_for_empty() -> None:
    assert suggest_annotation_from_query("") is None


def test_suggest_kind_and_severity() -> None:
    s = suggest_annotation_from_query("裂缝 紧急 大坝东侧")
    assert s is not None
    assert s["geom_kind"] == "line"
    assert s["severity"] == "critical"
    # Label should skip semantic tokens and take first substantive.
    assert s["label"] == "大坝东侧"


# ---- REST integration tests ----------------------------------------

async def test_search_free_text_matches_label(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    hit = await _mkann(
        client, tok, sid, label="东侧墙裂缝",
        geom_kind="line", geom_vertices=[[0, 0, 0], [1, 0, 0]],
        severity="high",
    )
    _ = await _mkann(client, tok, sid, label="传感器点位")

    r = await client.get(
        f"/api/v1/annotation-search/scenes/{sid}?query=东侧",
        headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    ids = [h["annotation"]["id"] for h in body["hits"]]
    assert hit["id"] in ids


async def test_search_semantic_kind_only_no_keywords(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    line = await _mkann(
        client, tok, sid, label="标注1",
        geom_kind="line", geom_vertices=[[0, 0, 0], [1, 0, 0]],
    )
    _pt = await _mkann(client, tok, sid, label="标注2")

    # "裂缝" 只触发几何语义, 无实际关键词命中 label.
    r = await client.get(
        f"/api/v1/annotation-search/scenes/{sid}?query=裂缝",
        headers=_h(tok),
    )
    body = r.json()
    ids = [h["annotation"]["id"] for h in body["hits"]]
    assert line["id"] in ids
    assert _pt["id"] not in ids


async def test_search_ranks_label_higher_than_description(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    labeled = await _mkann(
        client, tok, sid, label="断裂缺陷", description="常规巡检",
    )
    desc_only = await _mkann(
        client, tok, sid, label="常规点",
        description="附近发现断裂",
    )

    r = await client.get(
        f"/api/v1/annotation-search/scenes/{sid}?query=断裂",
        headers=_h(tok),
    )
    body = r.json()
    hits = body["hits"]
    # First hit should be the label match (score+3) not description (score+1).
    assert hits[0]["annotation"]["id"] == labeled["id"]
    assert hits[0]["score"] > hits[1]["score"]
    # matched_reasons should mention 'label' for first hit.
    assert any("label" in reason for reason in hits[0]["matched_reasons"])
    # And 'description' for second.
    ids_reasons = [
        (h["annotation"]["id"], h["matched_reasons"]) for h in hits
    ]
    desc_hit = next(h for h in ids_reasons if h[0] == desc_only["id"])
    assert any("描述" in r for r in desc_hit[1])


async def test_search_empty_query_returns_recent(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    await _mkann(client, tok, sid, label="a")
    await _mkann(client, tok, sid, label="b")
    r = await client.get(
        f"/api/v1/annotation-search/scenes/{sid}?query=", headers=_h(tok),
    )
    body = r.json()
    assert len(body["hits"]) == 2


async def test_search_cross_org_isolation(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    sid = uuid4()
    await _mkann(client, tok_a, sid, label="A org 裂缝",
                 geom_kind="line",
                 geom_vertices=[[0, 0, 0], [1, 0, 0]])
    r = await client.get(
        f"/api/v1/annotation-search/scenes/{sid}?query=裂缝",
        headers=_h(tok_b),
    )
    assert r.json()["hits"] == []


async def test_suggest_endpoint(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.get(
        "/api/v1/annotation-search/suggest?query=淤积区严重",
        headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["suggestion"]["geom_kind"] == "polygon"
    # "严重" -> critical severity
    assert body["suggestion"]["severity"] == "critical"


async def test_search_parsed_hints_exposed(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    r = await client.get(
        f"/api/v1/annotation-search/scenes/{sid}?query=紧急裂缝",
        headers=_h(tok),
    )
    parsed = r.json()["parsed"]
    assert parsed["raw"] == "紧急裂缝"
    assert "critical" in parsed["severities"]
    assert "line" in parsed["geom_kinds"]
