"""D2.2 · Scene annotation tests — 3DGS/4DGS markup layer."""
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


async def _mkuser() -> tuple[str, UUID, UUID]:
    uid, org = uuid4(), uuid4()
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(
            id=uid, email=f"ann+{uuid4().hex[:6]}@t.local",
            hashed_pw=hash_password("StrongPass!"),
            role="user", org_id=org,
        ))
        await s.commit()
    tok = create_access_token(user_id=uid, org_id=org, role="user")
    return tok, uid, org


def _pt(x: float = 0, y: float = 0, z: float = 0) -> list[list[float]]:
    return [[x, y, z]]


def _line() -> list[list[float]]:
    return [[0, 0, 0], [3, 4, 0]]  # length 5


def _polygon() -> list[list[float]]:
    return [[0, 0, 0], [10, 0, 0], [10, 5, 0], [0, 5, 0]]  # area 50


async def _mkann(client, tok: str, sid: UUID, **overrides) -> dict:
    payload = {
        "geom_kind": "point",
        "geom_vertices": _pt(),
        "label": "缺陷点",
        "severity": "high",
    }
    payload.update(overrides)
    r = await client.post(
        f"/api/v1/scenes/{sid}/annotations",
        headers=_h(tok), json=payload,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_and_list_annotation(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    ann = await _mkann(client, tok, sid)
    assert ann["scene_id"] == str(sid)
    assert ann["geom_kind"] == "point"
    assert ann["severity"] == "high"
    assert ann["resolved"] is False
    assert ann["geometry_summary"]["n_vertices"] == 1

    r = await client.get(
        f"/api/v1/scenes/{sid}/annotations", headers=_h(tok),
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_line_geometry_length_computed(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    ann = await _mkann(
        client, tok, sid,
        geom_kind="line",
        geom_vertices=_line(),
        label="裂缝1",
    )
    # 3-4-5 triangle, so length = 5.0
    assert ann["geometry_summary"]["length_m"] == 5.0


async def test_polygon_area_computed(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    ann = await _mkann(
        client, tok, sid,
        geom_kind="polygon",
        geom_vertices=_polygon(),
        label="淤积区",
    )
    assert ann["geometry_summary"]["area_m2"] == 50.0
    # perimeter = 2*(10+5) = 30
    assert ann["geometry_summary"]["perimeter_m"] == 30.0


async def test_invalid_geom_kind_rejected(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    r = await client.post(
        f"/api/v1/scenes/{sid}/annotations", headers=_h(tok),
        json={
            "geom_kind": "star",
            "geom_vertices": _pt(),
            "label": "x",
        },
    )
    assert r.status_code == 400


async def test_point_requires_exactly_one_vertex(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    r = await client.post(
        f"/api/v1/scenes/{sid}/annotations", headers=_h(tok),
        json={
            "geom_kind": "point",
            "geom_vertices": [[0, 0, 0], [1, 1, 1]],
            "label": "x",
        },
    )
    assert r.status_code == 400
    assert "exactly 1" in r.text


async def test_polygon_requires_three_vertices(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    r = await client.post(
        f"/api/v1/scenes/{sid}/annotations", headers=_h(tok),
        json={
            "geom_kind": "polygon",
            "geom_vertices": [[0, 0, 0], [1, 0, 0]],
            "label": "x",
        },
    )
    assert r.status_code == 400


async def test_severity_filter_and_layer_filter(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    await _mkann(client, tok, sid, severity="critical", layer="defect")
    await _mkann(client, tok, sid, severity="info", layer="note")
    await _mkann(client, tok, sid, severity="critical", layer="note")

    r = await client.get(
        f"/api/v1/scenes/{sid}/annotations?severity=critical",
        headers=_h(tok),
    )
    assert len(r.json()) == 2

    r = await client.get(
        f"/api/v1/scenes/{sid}/annotations?layer=defect", headers=_h(tok),
    )
    assert len(r.json()) == 1


async def test_frame_index_filter_returns_matching_plus_static(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    a_static = await _mkann(client, tok, sid, label="静态标注")
    a_f5 = await _mkann(
        client, tok, sid, label="第5帧", frame_index=5,
    )
    a_f10 = await _mkann(
        client, tok, sid, label="第10帧", frame_index=10,
    )

    r = await client.get(
        f"/api/v1/scenes/{sid}/annotations?frame_index=5", headers=_h(tok),
    )
    ids = {a["id"] for a in r.json()}
    assert a_static["id"] in ids
    assert a_f5["id"] in ids
    assert a_f10["id"] not in ids


async def test_update_and_resolve(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    ann = await _mkann(client, tok, sid, severity="high")
    r = await client.patch(
        f"/api/v1/annotations/{ann['id']}", headers=_h(tok),
        json={
            "label": "已整改的缺陷",
            "severity": "low",
            "resolved": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "已整改的缺陷"
    assert body["severity"] == "low"
    assert body["resolved"] is True


async def test_only_unresolved_filter(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    a1 = await _mkann(client, tok, sid, label="A")
    _a2 = await _mkann(client, tok, sid, label="B")
    await client.patch(
        f"/api/v1/annotations/{a1['id']}", headers=_h(tok),
        json={"resolved": True},
    )
    r = await client.get(
        f"/api/v1/scenes/{sid}/annotations?only_unresolved=true",
        headers=_h(tok),
    )
    assert len(r.json()) == 1
    assert r.json()[0]["label"] == "B"


async def test_delete_annotation(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    ann = await _mkann(client, tok, sid)
    r = await client.delete(
        f"/api/v1/annotations/{ann['id']}", headers=_h(tok),
    )
    assert r.status_code == 204
    r = await client.get(
        f"/api/v1/annotations/{ann['id']}", headers=_h(tok),
    )
    assert r.status_code == 404


async def test_cross_org_isolation(client) -> None:
    tok_a, _, _ = await _mkuser()
    tok_b, _, _ = await _mkuser()
    sid = uuid4()
    ann = await _mkann(client, tok_a, sid)

    # B cannot see A's annotation
    r = await client.get(
        f"/api/v1/annotations/{ann['id']}", headers=_h(tok_b),
    )
    assert r.status_code == 404

    r = await client.patch(
        f"/api/v1/annotations/{ann['id']}", headers=_h(tok_b),
        json={"resolved": True},
    )
    assert r.status_code == 404

    # Same scene_id but B lists nothing.
    r = await client.get(
        f"/api/v1/scenes/{sid}/annotations", headers=_h(tok_b),
    )
    assert r.json() == []


async def test_replies_thread(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    ann = await _mkann(client, tok, sid, label="裂缝")

    r = await client.post(
        f"/api/v1/annotations/{ann['id']}/replies", headers=_h(tok),
        json={"body": "已现场核查, 建议整改"},
    )
    assert r.status_code == 201

    r = await client.post(
        f"/api/v1/annotations/{ann['id']}/replies", headers=_h(tok),
        json={"body": "整改方案已提交"},
    )
    assert r.status_code == 201

    r = await client.get(
        f"/api/v1/annotations/{ann['id']}/replies", headers=_h(tok),
    )
    assert r.status_code == 200
    replies = r.json()
    assert len(replies) == 2
    # ordering: ASC by created_at
    assert replies[0]["body"] == "已现场核查, 建议整改"


async def test_reply_on_missing_annotation_404(client) -> None:
    tok, _, _ = await _mkuser()
    r = await client.post(
        f"/api/v1/annotations/{uuid4()}/replies", headers=_h(tok),
        json={"body": "hi"},
    )
    assert r.status_code == 404


async def test_stats_rollup(client) -> None:
    tok, _, _ = await _mkuser()
    sid = uuid4()
    a_hi = await _mkann(client, tok, sid, severity="high")
    await _mkann(client, tok, sid, severity="high")
    await _mkann(client, tok, sid, severity="info")
    await _mkann(client, tok, sid, severity="critical")

    # Resolve one.
    await client.patch(
        f"/api/v1/annotations/{a_hi['id']}", headers=_h(tok),
        json={"resolved": True},
    )

    r = await client.get(
        f"/api/v1/scenes/{sid}/annotation-stats", headers=_h(tok),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert body["unresolved"] == 3
    assert body["by_severity"]["high"] == 2
    assert body["by_severity"]["info"] == 1
    assert body["by_severity"]["critical"] == 1
