"""F4.3 · Copilot usage & org quota service.

- record_usage: producer-side, best-effort. Never raise.
- daily_rollup / persona_rollup / model_rollup: admin analytics.
- get_org_month_usage: current-month tokens & cost for a tenant.
- set_org_quota / get_org_quota: policy CRUD.
- check_quota: pre-request gate (soft/hard).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_usage import CopilotOrgQuota, CopilotUsage


log = logging.getLogger(__name__)


# Default pricing (cost_units per 1k tokens).
# Kept simple; a real deploy can pull from a pricing service.
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    # model_name → (prompt_price_per_1k, completion_price_per_1k)
    "ark-code-latest": (0.002, 0.006),
    "gpt-4o-mini": (0.00015, 0.0006),
    "glm-5.1": (0.001, 0.002),
    "default": (0.001, 0.002),
}


def _price(
    model: str, prompt_tokens: int, completion_tokens: int,
) -> float:
    p_price, c_price = DEFAULT_PRICING.get(
        model, DEFAULT_PRICING["default"],
    )
    return round(
        (prompt_tokens / 1000.0) * p_price
        + (completion_tokens / 1000.0) * c_price,
        4,
    )


# ------------------------- Record -------------------------

async def record_usage(
    db: AsyncSession, *,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    status: str = "ok",
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    persona: str | None = None,
    cost_units: float | None = None,
) -> uuid.UUID | None:
    """Insert one usage row; swallow errors and log.

    Producer (Copilot runtime) is not blocked by ledger failures.
    """
    try:
        if prompt_tokens < 0 or completion_tokens < 0:
            raise ValueError("token counts must be non-negative")
        if latency_ms < 0:
            raise ValueError("latency must be non-negative")
        if status not in ("ok", "error", "timeout", "cancelled"):
            status = "error"

        cu = (
            cost_units
            if cost_units is not None
            else _price(model, prompt_tokens, completion_tokens)
        )
        row = CopilotUsage(
            org_id=org_id, user_id=user_id,
            session_id=session_id, turn_id=turn_id,
            persona=persona, model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_units=Decimal(str(cu)),
            status=status,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id
    except Exception as e:  # noqa: BLE001
        log.warning(
            "record_usage failed model=%s err=%s", model, e,
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return None


# ------------------------- Analytics -------------------------

async def get_org_month_usage(
    db: AsyncSession, *, org_id: uuid.UUID | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Cumulative usage for the calendar month of `when` (default now)."""
    if when is None:
        when = datetime.now(timezone.utc)
    month_start = when.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    q = select(
        func.count().label("turns"),
        func.coalesce(
            func.sum(CopilotUsage.prompt_tokens), 0,
        ).label("prompt"),
        func.coalesce(
            func.sum(CopilotUsage.completion_tokens), 0,
        ).label("completion"),
        func.coalesce(
            func.sum(CopilotUsage.cost_units), 0,
        ).label("cost"),
        func.coalesce(
            func.avg(CopilotUsage.latency_ms), 0,
        ).label("avg_latency"),
        func.coalesce(
            func.sum(
                case((CopilotUsage.status != "ok", 1), else_=0),
            ), 0,
        ).label("errors"),
    ).where(CopilotUsage.created_at >= month_start)
    if org_id is not None:
        q = q.where(CopilotUsage.org_id == org_id)
    row = (await db.execute(q)).one()
    total_tokens = int(row.prompt) + int(row.completion)
    turns = int(row.turns)
    return {
        "turns": turns,
        "prompt_tokens": int(row.prompt),
        "completion_tokens": int(row.completion),
        "total_tokens": total_tokens,
        "cost_units": float(row.cost or 0),
        "avg_latency_ms": int(float(row.avg_latency or 0)),
        "errors": int(row.errors),
        "error_rate": (
            (int(row.errors) / turns) if turns > 0 else 0.0
        ),
        "month_start": month_start.isoformat(),
    }


async def daily_rollup(
    db: AsyncSession, *,
    org_id: uuid.UUID | None = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Per-day rollup for the last N days."""
    if days < 1:
        days = 1
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # Use func.date() for portability between PostgreSQL and SQLite.
    day_col = func.date(CopilotUsage.created_at).label("day")
    q = (
        select(
            day_col,
            func.count().label("turns"),
            func.coalesce(
                func.sum(CopilotUsage.prompt_tokens
                         + CopilotUsage.completion_tokens),
                0,
            ).label("tokens"),
            func.coalesce(
                func.sum(CopilotUsage.cost_units), 0,
            ).label("cost"),
        )
        .where(CopilotUsage.created_at >= since)
        .group_by(day_col)
        .order_by(day_col)
    )
    if org_id is not None:
        q = q.where(CopilotUsage.org_id == org_id)
    rows = (await db.execute(q)).all()
    out = []
    for r in rows:
        d = r.day
        if isinstance(d, datetime):
            d_str = d.date().isoformat()
        elif isinstance(d, date):
            d_str = d.isoformat()
        else:
            d_str = str(d)
        out.append({
            "day": d_str,
            "turns": int(r.turns),
            "tokens": int(r.tokens),
            "cost_units": float(r.cost or 0),
        })
    return out


async def persona_rollup(
    db: AsyncSession, *, org_id: uuid.UUID | None = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    q = (
        select(
            CopilotUsage.persona,
            func.count().label("turns"),
            func.coalesce(
                func.sum(CopilotUsage.prompt_tokens
                         + CopilotUsage.completion_tokens),
                0,
            ).label("tokens"),
            func.coalesce(
                func.sum(CopilotUsage.cost_units), 0,
            ).label("cost"),
            func.coalesce(
                func.avg(CopilotUsage.latency_ms), 0,
            ).label("avg_latency"),
        )
        .where(CopilotUsage.created_at >= since)
        .group_by(CopilotUsage.persona)
    )
    if org_id is not None:
        q = q.where(CopilotUsage.org_id == org_id)
    rows = (await db.execute(q)).all()
    out = []
    for r in rows:
        out.append({
            "persona": r.persona or "(none)",
            "turns": int(r.turns),
            "tokens": int(r.tokens),
            "cost_units": float(r.cost or 0),
            "avg_latency_ms": int(float(r.avg_latency or 0)),
        })
    out.sort(key=lambda x: -x["tokens"])
    return out


async def model_rollup(
    db: AsyncSession, *,
    days: int = 30,
) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    q = (
        select(
            CopilotUsage.model,
            func.count().label("turns"),
            func.coalesce(
                func.sum(CopilotUsage.prompt_tokens
                         + CopilotUsage.completion_tokens),
                0,
            ).label("tokens"),
            func.coalesce(
                func.sum(CopilotUsage.cost_units), 0,
            ).label("cost"),
        )
        .where(CopilotUsage.created_at >= since)
        .group_by(CopilotUsage.model)
        .order_by(func.count().desc())
    )
    rows = (await db.execute(q)).all()
    return [{
        "model": r.model,
        "turns": int(r.turns),
        "tokens": int(r.tokens),
        "cost_units": float(r.cost or 0),
    } for r in rows]


# ------------------------- Quota -------------------------

async def set_org_quota(
    db: AsyncSession, *,
    org_id: uuid.UUID,
    monthly_token_budget: int,
    hard_stop: bool = False,
) -> dict[str, Any]:
    if monthly_token_budget < 0:
        raise ValueError("monthly_token_budget must be non-negative")
    # Portable upsert: try update first; if no rows affected, insert.
    from sqlalchemy import update as sa_update, insert as sa_insert

    upd_stmt = (
        sa_update(CopilotOrgQuota)
        .where(CopilotOrgQuota.org_id == org_id)
        .values(
            monthly_token_budget=monthly_token_budget,
            hard_stop=hard_stop,
        )
    )
    res = await db.execute(upd_stmt)
    if res.rowcount == 0:
        ins_stmt = sa_insert(CopilotOrgQuota).values(
            org_id=org_id,
            monthly_token_budget=monthly_token_budget,
            hard_stop=hard_stop,
        )
        try:
            await db.execute(ins_stmt)
        except Exception:
            # Racing insert — retry update once.
            await db.execute(upd_stmt)
    await db.commit()
    q = (await get_org_quota(db, org_id=org_id))
    return q  # type: ignore[return-value]


async def get_org_quota(
    db: AsyncSession, *, org_id: uuid.UUID,
) -> dict[str, Any] | None:
    q = select(CopilotOrgQuota).where(
        CopilotOrgQuota.org_id == org_id,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        return None
    return {
        "org_id": str(row.org_id),
        "monthly_token_budget": int(row.monthly_token_budget),
        "hard_stop": bool(row.hard_stop),
        "updated_at": row.updated_at.isoformat()
        if row.updated_at else None,
    }


async def check_quota(
    db: AsyncSession, *, org_id: uuid.UUID,
) -> dict[str, Any]:
    """Pre-request gate: is this tenant over budget?

    Returns dict with: allowed, over_budget, budget, used, remaining,
    hard_stop, ratio.
    """
    q = await get_org_quota(db, org_id=org_id)
    if q is None or q["monthly_token_budget"] == 0:
        # No policy or 0 budget → unlimited.
        return {
            "allowed": True, "over_budget": False,
            "budget": 0, "used": 0, "remaining": None,
            "hard_stop": False, "ratio": 0.0,
        }

    usage = await get_org_month_usage(db, org_id=org_id)
    used = usage["total_tokens"]
    budget = q["monthly_token_budget"]
    over = used >= budget
    hard = bool(q["hard_stop"])
    allowed = not (over and hard)
    ratio = (used / budget) if budget > 0 else 0.0
    return {
        "allowed": allowed,
        "over_budget": over,
        "budget": budget,
        "used": used,
        "remaining": max(0, budget - used),
        "hard_stop": hard,
        "ratio": round(min(ratio, 999.0), 4),
    }
