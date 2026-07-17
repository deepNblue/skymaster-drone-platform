"""E3.3 · Detection alert rule service — CRUD + evaluation."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.detection_alert_rule import (
    DetectionAlertRule, VALID_ACTIONS,
)


log = logging.getLogger(__name__)


class AlertRuleError(Exception):
    pass


# ------------------------- CRUD -------------------------

async def create_rule(
    db: AsyncSession, *,
    org_id: uuid.UUID,
    name: str,
    label: str,
    min_member_count: int = 3,
    min_peak_confidence: float = 0.0,
    action: str = "log",
    cooldown_seconds: int = 300,
    notes: str | None = None,
) -> DetectionAlertRule:
    """Create a new rule after validating inputs."""
    if not name or not name.strip():
        raise AlertRuleError("name is required")
    if not label or not label.strip():
        raise AlertRuleError("label is required")
    if action not in VALID_ACTIONS:
        raise AlertRuleError(f"invalid action: {action}")
    if min_member_count < 1:
        raise AlertRuleError("min_member_count must be >= 1")
    if not (0.0 <= min_peak_confidence <= 1.0):
        raise AlertRuleError(
            "min_peak_confidence must be in [0, 1]",
        )
    if cooldown_seconds < 0:
        raise AlertRuleError("cooldown_seconds must be >= 0")

    rule = DetectionAlertRule(
        org_id=org_id,
        name=name.strip(),
        label=label.strip(),
        min_member_count=min_member_count,
        min_peak_confidence=min_peak_confidence,
        action=action,
        cooldown_seconds=cooldown_seconds,
        notes=notes,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def list_rules(
    db: AsyncSession, *,
    org_id: uuid.UUID,
    enabled_only: bool = False,
) -> list[DetectionAlertRule]:
    q = select(DetectionAlertRule).where(
        DetectionAlertRule.org_id == org_id,
    )
    if enabled_only:
        q = q.where(DetectionAlertRule.enabled.is_(True))
    q = q.order_by(DetectionAlertRule.created_at.desc())
    return list((await db.execute(q)).scalars().all())


async def get_rule(
    db: AsyncSession, *,
    org_id: uuid.UUID, rule_id: uuid.UUID,
) -> DetectionAlertRule:
    q = select(DetectionAlertRule).where(
        DetectionAlertRule.id == rule_id,
        DetectionAlertRule.org_id == org_id,
    )
    r = (await db.execute(q)).scalar_one_or_none()
    if r is None:
        raise AlertRuleError("rule not found")
    return r


async def update_rule(
    db: AsyncSession, *,
    org_id: uuid.UUID, rule_id: uuid.UUID,
    **kwargs: Any,
) -> DetectionAlertRule:
    rule = await get_rule(db, org_id=org_id, rule_id=rule_id)
    allowed = {
        "name", "label", "min_member_count", "min_peak_confidence",
        "action", "cooldown_seconds", "enabled", "notes",
    }
    for k, v in kwargs.items():
        if k not in allowed or v is None:
            continue
        if k == "action" and v not in VALID_ACTIONS:
            raise AlertRuleError(f"invalid action: {v}")
        if k == "min_member_count" and int(v) < 1:
            raise AlertRuleError("min_member_count must be >= 1")
        if k == "min_peak_confidence" and not (0.0 <= float(v) <= 1.0):
            raise AlertRuleError(
                "min_peak_confidence must be in [0, 1]",
            )
        setattr(rule, k, v)
    rule.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_rule(
    db: AsyncSession, *,
    org_id: uuid.UUID, rule_id: uuid.UUID,
) -> None:
    rule = await get_rule(db, org_id=org_id, rule_id=rule_id)
    await db.delete(rule)
    await db.commit()


# ------------------------- Matching -------------------------

def rule_matches_cluster(
    rule: DetectionAlertRule, cluster: dict[str, Any],
    *, now: datetime | None = None,
) -> bool:
    """Return True if a cluster satisfies rule thresholds AND
    the rule is not currently in cooldown."""
    if not rule.enabled:
        return False
    if rule.label != "*" and rule.label != cluster.get("label"):
        return False
    if cluster.get("member_count", 0) < rule.min_member_count:
        return False
    conf = float(cluster.get("peak_confidence") or 0)
    if conf < rule.min_peak_confidence:
        return False
    if rule.last_fired_at is not None and rule.cooldown_seconds > 0:
        now = now or datetime.now(timezone.utc)
        last = rule.last_fired_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last) < timedelta(
            seconds=rule.cooldown_seconds,
        ):
            return False
    return True


async def evaluate_rules(
    db: AsyncSession, *,
    org_id: uuid.UUID,
    clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Iterate enabled rules and match against clusters.

    Returns list of fire records:
        {rule_id, rule_name, action, label, member_count,
         peak_confidence, centroid_lat/lng, first_seen_at,
         last_seen_at}

    Cooldown enforcement: any rule that fires has ``last_fired_at``
    bumped, so subsequent evaluations within the cooldown window
    are suppressed.
    """
    rules = await list_rules(db, org_id=org_id, enabled_only=True)
    if not rules:
        return []
    fires: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for rule in rules:
        for c in clusters:
            if not rule_matches_cluster(rule, c, now=now):
                continue
            fires.append({
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "action": rule.action,
                "label": c.get("label"),
                "member_count": c.get("member_count"),
                "peak_confidence": c.get("peak_confidence"),
                "centroid_lat": c.get("centroid_lat"),
                "centroid_lng": c.get("centroid_lng"),
                "first_seen_at": _isofmt(c.get("first_seen_at")),
                "last_seen_at": _isofmt(c.get("last_seen_at")),
            })
            rule.last_fired_at = now
            # Only one fire per rule per evaluation call.
            break
    if fires:
        await db.commit()
    return fires


def _isofmt(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)
