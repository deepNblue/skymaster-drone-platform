"""RBAC role definitions — v1.0 permissions track.

Three canonical roles:

* ``viewer``   — read-only across the org (dashboard/monitoring)
* ``operator`` — create/modify missions, submit UOM reports, dispatch drones
* ``admin``    — everything above + user/organization management + approve UOM

The string values are what land in the JWT ``role`` claim and the
``users.role`` column, so DO NOT rename them.
"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


# Role hierarchy — higher rank includes all capabilities of lower.
_RANK = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


def has_at_least(actor: str, minimum: Role) -> bool:
    """Return True if ``actor`` role >= ``minimum`` in the hierarchy."""
    try:
        actor_role = Role(actor.lower())
    except ValueError:
        return False
    return _RANK[actor_role] >= _RANK[minimum]


# Convenience predicates
def is_admin(actor: str) -> bool:
    return has_at_least(actor, Role.ADMIN)


def is_operator_or_above(actor: str) -> bool:
    return has_at_least(actor, Role.OPERATOR)
