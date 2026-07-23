"""Three-Officer Separation of Duty — 等保 2.0 三级核心机制.

Enforces the "3-officer" principle: no single person can operate, authorize,
and audit at the same time. Adds an *orthogonal* dimension to the existing
business ``role`` column:

    business role  ∈  {viewer, operator, admin, ...}   ← 业务权限
    officer_role   ∈  {None,
                       system_officer,   # 系统员 · 配置、部署、备份
                       security_officer, # 安全员 · 授权、密钥、策略
                       audit_officer}    # 审计员 · 只读日志、生成报表

Hard rules encoded here:

  1. A user may hold **at most one** officer_role at a time.
  2. An ``admin`` user cannot also hold an officer_role (业务超管 vs 合规三员
     必须由不同自然人担任).
  3. Assigning / clearing an officer_role requires the caller to be a
     **security_officer**.  (No self-elevation.)
  4. Audit officer can never mutate the system — read-only endpoints only.
  5. Compliance toggle (SM3/SM4) requires **security_officer**, not admin,
     once at least one security_officer exists (bootstrap grace period
     otherwise).

Permission matrix (per action):

    action                             sys  sec  aud  admin
    ----------------------------------------------------------
    users.create/update/delete          ✔   ✖    ✖    ✔
    users.grant_officer                 ✖   ✔    ✖    ✖
    compliance.toggle                   ✖   ✔    ✖    ✔ (grace)
    audit.read                          ✖   ✖    ✔    ✔
    audit.export                        ✖   ✖    ✔    ✖
    keys.rotate                         ✖   ✔    ✖    ✖
    backup.create                       ✔   ✖    ✖    ✔
    backup.restore                      ✔   ✔    ✖    ✖   (needs both)
"""
from __future__ import annotations

from typing import Callable, Iterable

from fastapi import Depends, HTTPException

from app.deps import get_current_user
from app.models.user import User

OFFICER_ROLES = {"system_officer", "security_officer", "audit_officer"}


# --- Permission matrix -----------------------------------------------------


# Each action lists which roles may perform it. "*" means any authenticated
# user. Business ``role`` and ``officer_role`` are BOTH checked — user
# passes if ANY of their roles is in the allowed set.
PERMISSION_MATRIX: dict[str, set[str]] = {
    # Officer management (only security_officer can grant/revoke officer roles)
    "officer.grant": {"security_officer"},
    "officer.revoke": {"security_officer"},
    "officer.list": {"security_officer", "audit_officer", "admin"},

    # System configuration
    "users.write": {"system_officer", "admin"},
    "users.read": {"system_officer", "security_officer", "audit_officer", "admin"},

    # Compliance / crypto — security_officer once bootstrapped
    "compliance.toggle": {"security_officer", "admin"},  # admin during grace
    "compliance.read": {"security_officer", "audit_officer", "admin"},
    "keys.rotate": {"security_officer"},

    # Audit
    "audit.read": {"audit_officer", "admin"},
    "audit.export": {"audit_officer"},
    "audit.chain_verify": {"audit_officer", "security_officer"},

    # Backup / restore
    "backup.create": {"system_officer", "admin"},
    "backup.restore": {"system_officer", "security_officer"},  # BOTH must sign
}


def user_role_set(user: User) -> set[str]:
    roles = {user.role}
    if user.officer_role:
        roles.add(user.officer_role)
    return roles


def can(user: User, action: str) -> bool:
    allowed = PERMISSION_MATRIX.get(action)
    if allowed is None:  # unknown action — deny by default
        return False
    return bool(user_role_set(user) & allowed)


def require_action(action: str) -> Callable:
    """FastAPI dependency factory.

    Usage::

        @router.post("/x", dependencies=[Depends(require_action("keys.rotate"))])
    """
    async def dep(user: User = Depends(get_current_user)) -> User:
        if not can(user, action):
            raise HTTPException(
                status_code=403,
                detail=f"三员分立 · 该操作需要权限 {action!r}，"
                       f"当前身份 role={user.role!r} officer={user.officer_role!r}",
            )
        return user
    return dep


def require_officer(*officers: str) -> Callable:
    """Require the caller to hold one of the specified officer_role values."""
    valid = set(officers)
    async def dep(user: User = Depends(get_current_user)) -> User:
        if user.officer_role not in valid:
            raise HTTPException(
                status_code=403,
                detail=f"三员分立 · 需要 {sorted(valid)} 身份，"
                       f"当前 {user.officer_role!r}",
            )
        return user
    return dep


# --- Assignment validation -------------------------------------------------


def validate_officer_assignment(target: User, new_officer: str | None) -> None:
    """Raise HTTPException if the assignment violates SoD invariants."""
    if new_officer is not None and new_officer not in OFFICER_ROLES:
        raise HTTPException(400, f"invalid officer_role {new_officer!r}")
    # Rule 2: admin cannot double as officer.
    if new_officer is not None and target.role == "admin":
        raise HTTPException(
            409,
            "违反三员分立 · admin 账号不得兼任三员身份，请先降级 role",
        )


def dual_control_check(actor: User, cosigner: User | None, action: str) -> None:
    """Enforce dual-officer control for high-risk ops (e.g. backup.restore).

    Requires TWO distinct officers whose combined roles cover the action.
    """
    allowed = PERMISSION_MATRIX.get(action, set())
    if cosigner is None:
        raise HTTPException(400, f"{action} 需要双人协签，缺少 cosigner")
    if actor.id == cosigner.id:
        raise HTTPException(400, "双人协签不能是同一账号")
    combined = user_role_set(actor) | user_role_set(cosigner)
    if not (combined & allowed):
        raise HTTPException(403, f"两名协签者身份合集不满足 {action} 要求")
    # Both must be officers (not just admins).
    if not actor.officer_role or not cosigner.officer_role:
        raise HTTPException(403, f"{action} 双人协签双方必须均为三员身份")
    if actor.officer_role == cosigner.officer_role:
        raise HTTPException(403, "双人协签双方三员身份不能相同")
