"""Users & Organizations CRUD — v1.0 multi-tenant admin API.

Endpoints are admin-only. Provides:

    POST   /api/v1/admin/organizations         # create org
    GET    /api/v1/admin/organizations         # list orgs
    POST   /api/v1/admin/users                 # invite/create user
    GET    /api/v1/admin/users                 # list users (filter by org)
    PATCH  /api/v1/admin/users/{id}            # change role / org
    DELETE /api/v1/admin/users/{id}            # deactivate

Password reset & self-service registration is out of scope for this round;
admins provision users directly.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Role, require_min_role
from app.models.organization import Organization
from app.models.user import User
from app.services.auth import hash_password
from app.services.rbac import Role as RBACRole

router = APIRouter(prefix="/admin", tags=["admin"])


# ---- Pydantic schemas ----------------------------------------------------
class OrgCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)


class OrgOut(BaseModel):
    id: UUID
    name: str

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=200)
    role: str = Field(default="viewer")
    org_id: UUID | None = None


class UserPatch(BaseModel):
    role: str | None = None
    org_id: UUID | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: UUID
    email: str
    role: str
    org_id: UUID | None
    is_active: bool

    class Config:
        from_attributes = True


# ---- Organizations -------------------------------------------------------
@router.post("/organizations", response_model=OrgOut, status_code=201)
async def create_org(
    body: OrgCreate,
    _admin=Depends(require_min_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    existing = await db.execute(
        select(Organization).where(Organization.name == body.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(409, f"organization '{body.name}' already exists")
    org = Organization(id=uuid4(), name=body.name)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/organizations", response_model=list[OrgOut])
async def list_orgs(
    _admin=Depends(require_min_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[Organization]:
    r = await db.execute(select(Organization))
    return list(r.scalars().all())


@router.patch("/organizations/{org_id}", response_model=OrgOut)
async def patch_org(
    org_id: UUID,
    body: OrgCreate,
    _admin=Depends(require_min_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    r = await db.execute(select(Organization).where(Organization.id == org_id))
    org = r.scalar_one_or_none()
    if org is None:
        raise HTTPException(404, f"organization {org_id} not found")
    # Uniqueness re-check
    existing = await db.execute(
        select(Organization).where(
            Organization.name == body.name, Organization.id != org_id
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(409, f"name '{body.name}' already taken")
    org.name = body.name
    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/organizations/{org_id}")
async def delete_org(
    org_id: UUID,
    _admin=Depends(require_min_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.execute(select(Organization).where(Organization.id == org_id))
    org = r.scalar_one_or_none()
    if org is None:
        raise HTTPException(404, f"organization {org_id} not found")
    # Hard-delete: cascade drops users via FK ondelete=CASCADE. Refuse if
    # any active user exists — force admin to migrate users first.
    r = await db.execute(
        select(User).where(User.org_id == org_id, User.is_active.is_(True))
    )
    if r.scalars().first() is not None:
        raise HTTPException(
            409,
            "organization has active users; migrate/deactivate them first",
        )
    await db.delete(org)
    await db.commit()
    return {"ok": True, "deleted": str(org_id)}


# ---- Users ---------------------------------------------------------------
def _validate_role(role: str) -> str:
    try:
        return RBACRole(role.lower()).value
    except ValueError:
        raise HTTPException(400, f"invalid role: {role}")


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    _admin=Depends(require_min_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> User:
    role = _validate_role(body.role)
    existing = await db.execute(
        select(User).where(User.email == body.email.lower())
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(409, f"user {body.email} already exists")
    if body.org_id is not None:
        exists = await db.execute(
            select(Organization).where(Organization.id == body.org_id)
        )
        if exists.scalar_one_or_none() is None:
            raise HTTPException(404, f"org_id={body.org_id} not found")
    u = User(
        id=uuid4(),
        email=body.email.lower(),
        hashed_pw=hash_password(body.password),
        role=role,
        org_id=body.org_id,
        is_active=True,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@router.get("/users", response_model=list[UserOut])
async def list_users(
    org_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None, description="search email substring"),
    role: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    _admin=Depends(require_min_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[User]:
    stmt = select(User)
    if org_id is not None:
        stmt = stmt.where(User.org_id == org_id)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q.lower()}%"))
    if role:
        stmt = stmt.where(User.role == role.lower())
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    stmt = stmt.limit(500)
    r = await db.execute(stmt)
    return list(r.scalars().all())


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: UUID,
    body: UserPatch,
    _admin=Depends(require_min_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> User:
    r = await db.execute(select(User).where(User.id == user_id))
    u = r.scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"user {user_id} not found")
    if body.role is not None:
        u.role = _validate_role(body.role)
    if body.org_id is not None:
        exists = await db.execute(
            select(Organization).where(Organization.id == body.org_id)
        )
        if exists.scalar_one_or_none() is None:
            raise HTTPException(404, f"org_id={body.org_id} not found")
        u.org_id = body.org_id
    if body.is_active is not None:
        u.is_active = body.is_active
    await db.commit()
    await db.refresh(u)
    return u


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: UUID,
    _admin=Depends(require_min_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.execute(select(User).where(User.id == user_id))
    u = r.scalar_one_or_none()
    if u is None:
        raise HTTPException(404, f"user {user_id} not found")
    # Soft-delete: mark inactive rather than losing audit trail.
    u.is_active = False
    await db.commit()
    return {"ok": True, "deactivated": str(user_id)}
