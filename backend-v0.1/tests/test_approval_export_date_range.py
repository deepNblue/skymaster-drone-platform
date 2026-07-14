"""T7.11 — created_from/created_to filter for approval exports."""
from __future__ import annotations

import io
import csv
import zipfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


from urllib.parse import quote


def _iso(dt):
    """URL-encode ISO datetime — '+' in tz offset must not become ' '."""
    return quote(dt.isoformat())


def _h(t): return {"Authorization": f"Bearer {t}"}


async def _mkuser(email: str, role: str = "user"):
    from app.db import engine
    from app.models.user import User
    from app.services.auth import create_access_token, hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker
    uid = uuid4()
    org_id = uuid4()
    email = email.replace("@", f"+{uuid4().hex[:6]}@")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        s.add(User(id=uid, email=email,
                   hashed_pw=hash_password("StrongPass!"),
                   role=role, org_id=org_id))
        await s.commit()
    return create_access_token(user_id=uid, org_id=org_id, role=role), org_id


async def _mkapproval(client, tok, title="a"):
    now = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/approvals",
        json={
            "title": title, "purpose": "date-filter",
            "category": "routine",
            "aircraft_reg": f"N-{uuid4().hex[:6].upper()}",
            "aircraft_model": "M300", "max_alt_m": 100,
            "area_polygon": [[104.0, 30.6], [104.02, 30.6],
                             [104.02, 30.62], [104.0, 30.62]],
            "start_ts": (now + timedelta(hours=1)).isoformat(),
            "end_ts": (now + timedelta(hours=3)).isoformat(),
        },
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _set_created_at(pid, dt):
    """Backdate an approval so we can test date-range filters."""
    from uuid import UUID as _UUID
    from app.db import engine
    from app.models.flight_approval import FlightApproval
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import update
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with S() as s:
        await s.execute(
            update(FlightApproval)
            .where(FlightApproval.id == _UUID(pid))
            .values(created_at=dt)
        )
        await s.commit()


@pytest.mark.asyncio
async def test_csv_export_date_range(client):
    tok, _ = await _mkuser("dr1@t711.com")
    old_id = await _mkapproval(client, tok, "old")
    mid_id = await _mkapproval(client, tok, "mid")
    new_id = await _mkapproval(client, tok, "new")

    now = datetime.now(timezone.utc)
    await _set_created_at(old_id, now - timedelta(days=10))
    await _set_created_at(mid_id, now - timedelta(days=5))
    await _set_created_at(new_id, now - timedelta(days=1))

    # No filter → all 3
    r = await client.get("/api/v1/approvals/export.csv", headers=_h(tok))
    assert r.headers["x-row-count"] == "3"

    # created_from → skip 'old'
    frm = _iso(now - timedelta(days=7))
    r = await client.get(
        f"/api/v1/approvals/export.csv?created_from={frm}",
        headers=_h(tok),
    )
    assert r.status_code == 200, r.text
    assert r.headers["x-row-count"] == "2"
    ids_in_csv = _csv_ids(r.content)
    assert old_id not in ids_in_csv
    assert mid_id in ids_in_csv
    assert new_id in ids_in_csv

    # created_to → skip 'new'
    to = _iso(now - timedelta(days=2))
    r = await client.get(
        f"/api/v1/approvals/export.csv?created_to={to}",
        headers=_h(tok),
    )
    assert r.headers["x-row-count"] == "2"
    ids_in_csv = _csv_ids(r.content)
    assert new_id not in ids_in_csv

    # Both bounds → only mid
    r = await client.get(
        f"/api/v1/approvals/export.csv?created_from={frm}&created_to={to}",
        headers=_h(tok),
    )
    assert r.headers["x-row-count"] == "1"
    assert _csv_ids(r.content) == [mid_id]


@pytest.mark.asyncio
async def test_zip_export_date_range(client):
    tok, _ = await _mkuser("dr2@t711.com")
    old_id = await _mkapproval(client, tok, "old")
    new_id = await _mkapproval(client, tok, "new")

    now = datetime.now(timezone.utc)
    await _set_created_at(old_id, now - timedelta(days=10))
    await _set_created_at(new_id, now - timedelta(hours=1))

    frm = _iso(now - timedelta(days=3))
    r = await client.get(
        f"/api/v1/approvals/export/certificates.zip?created_from={frm}",
        headers=_h(tok),
    )
    assert r.status_code == 200
    assert r.headers["x-row-count"] == "1"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert f"approval-{new_id}.pdf" in names
    assert f"approval-{old_id}.pdf" not in names


def _csv_ids(raw: bytes) -> list[str]:
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    header = rows[0]
    id_col = header.index("id")
    return [row[id_col] for row in rows[1:]]
