"""Tests for R19 三员分立 — SoD matrix + officer grant/revoke + dual-sign."""
from __future__ import annotations

from uuid import uuid4

import pytest


async def _make_user(email: str, role: str = "operator", officer: str | None = None) -> str:
    from app.db import engine
    from app.models.user import User
    from app.services.auth import hash_password
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid4()
    async with Session() as s:
        s.add(User(
            id=uid, email=email,
            hashed_pw=hash_password("StrongPassW0rd#"),
            role=role, officer_role=officer,
        ))
        await s.commit()
    return str(uid)


async def _login(client, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPassW0rd#"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# --------------------------------------------------------------------
# Matrix module — pure logic
# --------------------------------------------------------------------


def test_permission_matrix_shape():
    from app.services.officer_matrix import (
        OFFICER_ROLES, PERMISSION_MATRIX,
    )
    assert OFFICER_ROLES == {"system_officer", "security_officer", "audit_officer"}
    for action, roles in PERMISSION_MATRIX.items():
        assert isinstance(roles, set), action


def test_can_action():
    from app.services.officer_matrix import can
    class U:  # tiny mock
        def __init__(self, role, officer=None):
            self.role, self.officer_role = role, officer

    sec = U("operator", "security_officer")
    aud = U("operator", "audit_officer")
    sys_ = U("operator", "system_officer")
    admin = U("admin")

    # Only security_officer can grant officer roles
    assert can(sec, "officer.grant")
    assert not can(aud, "officer.grant")
    assert not can(sys_, "officer.grant")
    assert not can(admin, "officer.grant")   # admin cannot self-promote

    # Only audit_officer can export audit
    assert can(aud, "audit.export")
    assert not can(sec, "audit.export")
    assert not can(admin, "audit.export")

    # Compliance toggle: security_officer or admin (grace)
    assert can(sec, "compliance.toggle")
    assert can(admin, "compliance.toggle")

    # Unknown action defaults to deny
    assert not can(sec, "made.up.action")


def test_validate_officer_assignment_rejects_admin():
    from app.services.officer_matrix import validate_officer_assignment
    from fastapi import HTTPException

    class U:
        role = "admin"; officer_role = None

    with pytest.raises(HTTPException) as ei:
        validate_officer_assignment(U(), "security_officer")
    assert ei.value.status_code == 409

    with pytest.raises(HTTPException):
        validate_officer_assignment(U(), "made-up-role")


def test_dual_control_check():
    from app.services.officer_matrix import dual_control_check
    from fastapi import HTTPException

    class U:
        def __init__(self, uid, role, officer):
            self.id, self.role, self.officer_role = uid, role, officer

    sys_ = U("A", "operator", "system_officer")
    sec = U("B", "operator", "security_officer")
    sec2 = U("C", "operator", "security_officer")

    # Two distinct officers with different officer_role → pass
    dual_control_check(sys_, sec, "backup.restore")

    # Same person → reject
    with pytest.raises(HTTPException):
        dual_control_check(sys_, sys_, "backup.restore")

    # Missing cosigner → reject
    with pytest.raises(HTTPException):
        dual_control_check(sys_, None, "backup.restore")

    # Two security officers (same officer_role) → reject
    with pytest.raises(HTTPException):
        dual_control_check(sec, sec2, "backup.restore")


# --------------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_officer_by_security_officer(client):
    sec_id = await _make_user("sec1@x.com", officer="security_officer")
    target_id = await _make_user("target1@x.com")

    tok = await _login(client, "sec1@x.com")
    r = await client.post(
        "/api/v1/admin/officers/grant",
        json={"user_id": target_id, "officer_role": "audit_officer"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["officer_role"] == "audit_officer"


@pytest.mark.asyncio
async def test_admin_cannot_grant_officer(client):
    """Admin business role is orthogonal — cannot grant officer roles."""
    admin_id = await _make_user("adm2@x.com", role="admin")
    target_id = await _make_user("target2@x.com")
    tok = await _login(client, "adm2@x.com")
    r = await client.post(
        "/api/v1/admin/officers/grant",
        json={"user_id": target_id, "officer_role": "audit_officer"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cannot_grant_officer_to_admin(client):
    sec_id = await _make_user("sec3@x.com", officer="security_officer")
    admin_id = await _make_user("adm3@x.com", role="admin")
    tok = await _login(client, "sec3@x.com")
    r = await client.post(
        "/api/v1/admin/officers/grant",
        json={"user_id": admin_id, "officer_role": "audit_officer"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 409  # admin cannot double as officer


@pytest.mark.asyncio
async def test_cannot_self_grant(client):
    sec_id = await _make_user("sec4@x.com", officer="security_officer")
    tok = await _login(client, "sec4@x.com")
    r = await client.post(
        "/api/v1/admin/officers/grant",
        json={"user_id": sec_id, "officer_role": "audit_officer"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_revoke_officer(client):
    sec_id = await _make_user("sec5@x.com", officer="security_officer")
    target_id = await _make_user("target5@x.com", officer="audit_officer")
    tok = await _login(client, "sec5@x.com")
    r = await client.post(
        "/api/v1/admin/officers/revoke",
        json={"user_id": target_id},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["officer_role"] is None


@pytest.mark.asyncio
async def test_matrix_endpoint(client):
    sec_id = await _make_user("sec6@x.com", officer="security_officer")
    tok = await _login(client, "sec6@x.com")
    r = await client.get(
        "/api/v1/admin/officers/matrix",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "officers" in body and "matrix" in body
    assert "officer.grant" in body["matrix"]


@pytest.mark.asyncio
async def test_dual_sign_endpoint(client):
    sys_id = await _make_user("sys7@x.com", officer="system_officer")
    sec_id = await _make_user("sec7@x.com", officer="security_officer")
    tok = await _login(client, "sys7@x.com")
    r = await client.post(
        "/api/v1/admin/officers/dual-sign",
        json={"action": "backup.restore", "cosigner_id": sec_id},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_dual_sign_rejects_same_officer_role(client):
    sec_a = await _make_user("seca@x.com", officer="security_officer")
    sec_b = await _make_user("secb@x.com", officer="security_officer")
    tok = await _login(client, "seca@x.com")
    r = await client.post(
        "/api/v1/admin/officers/dual-sign",
        json={"action": "backup.restore", "cosigner_id": sec_b},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403
