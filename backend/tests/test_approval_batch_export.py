"""T7.8 — Batch approval export (CSV + ZIP of PDFs)."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


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
            "title": title,
            "purpose": "batch export test, 光电勘测",
            "category": "routine",
            "aircraft_reg": f"N-{uuid4().hex[:6].upper()}",
            "aircraft_model": "M300",
            "max_alt_m": 100,
            "area_polygon": [
                [104.0, 30.6], [104.02, 30.6],
                [104.02, 30.62], [104.0, 30.62],
            ],
            "start_ts": (now + timedelta(hours=1)).isoformat(),
            "end_ts": (now + timedelta(hours=3)).isoformat(),
        },
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_approvals_csv_export(client):
    tok, _ = await _mkuser("e1@t78.com")
    ids = []
    for i in range(3):
        ids.append(await _mkapproval(client, tok, title=f"ex-{i}"))

    r = await client.get("/api/v1/approvals/export.csv", headers=_h(tok))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers.get("x-row-count") == "3"
    assert r.content[:3] == b"\xef\xbb\xbf"  # BOM

    text = r.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    header = rows[0]
    body = rows[1:]
    assert "id" in header
    assert "authorities" in header
    assert len(body) == 3
    # Chinese preserved
    joined = " ".join(" ".join(r) for r in body)
    assert "光电勘测" in joined


@pytest.mark.asyncio
async def test_approvals_csv_tenant_isolation(client):
    tok_a, _ = await _mkuser("ea@t78.com")
    tok_b, _ = await _mkuser("eb@t78.com")
    for i in range(2):
        await _mkapproval(client, tok_a, title=f"a-{i}")
    await _mkapproval(client, tok_b, title="b-solo")

    r = await client.get("/api/v1/approvals/export.csv", headers=_h(tok_a))
    assert r.headers["x-row-count"] == "2"
    r = await client.get("/api/v1/approvals/export.csv", headers=_h(tok_b))
    assert r.headers["x-row-count"] == "1"


@pytest.mark.asyncio
async def test_approvals_csv_status_filter(client):
    tok, _ = await _mkuser("es@t78.com")
    aid = await _mkapproval(client, tok, title="pending")

    r = await client.get(
        "/api/v1/approvals/export.csv?status=draft", headers=_h(tok)
    )
    assert r.headers["x-row-count"] == "1"

    r = await client.get(
        "/api/v1/approvals/export.csv?status=approved", headers=_h(tok)
    )
    assert r.headers["x-row-count"] == "0"


@pytest.mark.asyncio
async def test_certificates_zip_export(client):
    tok, _ = await _mkuser("z1@t78.com")
    ids = []
    for i in range(2):
        ids.append(await _mkapproval(client, tok, title=f"zip-{i}"))

    r = await client.get(
        "/api/v1/approvals/export/certificates.zip", headers=_h(tok)
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers.get("x-row-count") == "2"

    # Parse the ZIP
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "INDEX.csv" in names
    pdf_files = [n for n in names if n.endswith(".pdf")]
    assert len(pdf_files) == 2, names
    for aid in ids:
        assert f"approval-{aid}.pdf" in names

    # PDFs are actually PDFs
    for pf in pdf_files:
        data = zf.read(pf)
        assert data[:5] == b"%PDF-", f"{pf} not a PDF"
        assert len(data) > 1000

    # INDEX.csv has the right shape
    idx_data = zf.read("INDEX.csv").decode("utf-8-sig")
    reader = csv.reader(io.StringIO(idx_data))
    idx_rows = list(reader)
    assert idx_rows[0] == [
        "filename", "id", "title", "aircraft_reg", "status",
        "max_alt_m", "created_at",
    ]
    assert len(idx_rows) - 1 == 2


@pytest.mark.asyncio
async def test_certificates_zip_empty_org(client):
    tok, _ = await _mkuser("z0@t78.com")
    r = await client.get(
        "/api/v1/approvals/export/certificates.zip", headers=_h(tok)
    )
    assert r.status_code == 200
    assert r.headers["x-row-count"] == "0"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    # Should still contain INDEX.csv (headers only)
    assert "INDEX.csv" in zf.namelist()
    idx_data = zf.read("INDEX.csv").decode("utf-8-sig")
    reader = csv.reader(io.StringIO(idx_data))
    idx_rows = list(reader)
    assert len(idx_rows) == 1  # just the header row
