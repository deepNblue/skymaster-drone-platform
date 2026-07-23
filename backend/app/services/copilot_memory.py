"""Copilot 长期记忆服务 (v2.1 E2.3).

功能:
- CRUD: 增/删/改 memories
- Search: 基于关键词的加权检索 (LIKE + weight + recency + hit_count)
- TTL 清理: 后台定期跑 ``purge_expired``
- Auto-consolidation: 从 CopilotTrace 中抽取用户偏好 (F5 时增强)

Ranking 公式:
   score = weight
         + recency_bonus  (30 天内衰减)
         + hit_bonus      (min(20, log2(1+hit_count)*5))
         - overlength_penalty  (content 过长时略降)

第一版不引 embedding, 因为:
- 尚无 GPU 常驻推理
- 检索规模一般 < 10K/租户
- 后续加 ``embedding`` 列即可平滑升级
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.copilot_memory import CopilotMemory

# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
@dataclass
class ScoredMemory:
    memory: CopilotMemory
    score: float
    reason: str  # human-readable ranking hint


def _recency_bonus(created: datetime | None, half_life_days: float = 30.0) -> float:
    if not created:
        return 0.0
    now = datetime.now(timezone.utc)
    delta_days = (now - created.replace(tzinfo=timezone.utc)).total_seconds() / 86400.0
    if delta_days < 0:
        return 20.0
    return 20.0 * math.exp(-delta_days / half_life_days)


def _hit_bonus(count: int) -> float:
    if count <= 0:
        return 0.0
    return min(20.0, math.log2(1 + count) * 5.0)


def _length_penalty(content: str) -> float:
    if len(content) > 800:
        return 5.0
    return 0.0


def rank(mem: CopilotMemory) -> tuple[float, str]:
    r = _recency_bonus(mem.created_at)
    h = _hit_bonus(mem.hit_count)
    p = _length_penalty(mem.content)
    score = mem.weight + r + h - p
    reason = f"w={mem.weight} +r={r:.1f} +h={h:.1f} -p={p:.1f}"
    return score, reason


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
async def create_memory(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID | None,
    kind: str,
    content: str,
    scope: str = "user",
    key: str | None = None,
    tags: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    ttl_days: int | None = None,
    weight: int = 50,
    source_trace_id: UUID | None = None,
) -> CopilotMemory:
    if scope not in ("user", "org"):
        raise ValueError(f"invalid scope: {scope}")
    if kind not in ("preference", "fact", "task_history", "insight"):
        raise ValueError(f"invalid kind: {kind}")
    weight = max(0, min(100, weight))

    # Dedup by (org, user, kind, key) — if key set, upsert
    if key:
        row = await _find_by_key(db, org_id=org_id, user_id=user_id, kind=kind, key=key)
        if row is not None:
            row.content = content
            row.tags = tags
            row.meta = meta
            row.weight = weight
            row.ttl_days = ttl_days
            row.scope = scope
            await db.commit()
            await db.refresh(row)
            return row

    mem = CopilotMemory(
        org_id=org_id,
        user_id=user_id,
        kind=kind,
        scope=scope,
        key=key,
        content=content,
        tags=tags,
        meta=meta,
        ttl_days=ttl_days,
        weight=weight,
        source_trace_id=source_trace_id,
    )
    db.add(mem)
    await db.commit()
    await db.refresh(mem)
    return mem


async def _find_by_key(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID | None,
    kind: str,
    key: str,
) -> CopilotMemory | None:
    stmt = select(CopilotMemory).where(
        and_(
            CopilotMemory.org_id == org_id,
            CopilotMemory.kind == kind,
            CopilotMemory.key == key,
        )
    )
    if user_id is not None:
        stmt = stmt.where(
            or_(CopilotMemory.user_id == user_id, CopilotMemory.scope == "org")
        )
    res = await db.execute(stmt.limit(1))
    return res.scalar_one_or_none()


async def delete_memory(
    db: AsyncSession, *, org_id: UUID, memory_id: UUID
) -> bool:
    res = await db.execute(
        select(CopilotMemory).where(
            and_(CopilotMemory.id == memory_id, CopilotMemory.org_id == org_id)
        )
    )
    mem = res.scalar_one_or_none()
    if mem is None:
        return False
    await db.delete(mem)
    await db.commit()
    return True


async def touch(db: AsyncSession, *, memory_ids: list[UUID]) -> None:
    """Bump hit_count + last_hit_at for the given memories."""
    if not memory_ids:
        return
    res = await db.execute(
        select(CopilotMemory).where(CopilotMemory.id.in_(memory_ids))
    )
    for m in res.scalars():
        m.hit_count += 1
        m.last_hit_at = datetime.now(timezone.utc)
    await db.commit()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _keyword_hit(text_val: str, keywords: list[str]) -> int:
    if not keywords:
        return 0
    hits = 0
    lower = text_val.lower()
    for kw in keywords:
        if kw.lower() in lower:
            hits += 1
    return hits


async def search_memory(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID | None,
    query: str = "",
    kinds: list[str] | None = None,
    tags: list[str] | None = None,
    top_k: int = 5,
) -> list[ScoredMemory]:
    """Search + rank memories accessible to (org_id, user_id)."""
    # Access filter: (own user_id OR scope=org OR user_id IS NULL)
    stmt = select(CopilotMemory).where(CopilotMemory.org_id == org_id)
    if user_id is not None:
        stmt = stmt.where(
            or_(
                CopilotMemory.user_id == user_id,
                CopilotMemory.scope == "org",
            )
        )
    if kinds:
        stmt = stmt.where(CopilotMemory.kind.in_(kinds))

    # Coarse LIKE if query provided (case-insensitive fall back)
    keywords = [w.strip() for w in query.split() if w.strip()]
    # For CJK-heavy prompts without whitespace, also try the raw query as a
    # single substring — otherwise we get 0 rows for "帮我安排巡检任务" vs
    # a stored preference "巡检默认时长 40 分钟".
    if query.strip() and len(keywords) <= 1:
        keywords = [query.strip()]

    keyword_stmt = stmt
    for kw in keywords[:5]:
        keyword_stmt = keyword_stmt.where(
            CopilotMemory.content.ilike(f"%{kw}%")
        )

    keyword_stmt = keyword_stmt.order_by(
        desc(CopilotMemory.created_at)
    ).limit(200)
    res = await db.execute(keyword_stmt)
    rows = list(res.scalars().all())

    # Fallback: if strict LIKE filter returns nothing, expand to the
    # unfiltered set and rely purely on the ranking function. This makes
    # Chinese (no whitespace) queries workable without a tokenizer.
    if not rows and keywords:
        stmt = stmt.order_by(desc(CopilotMemory.created_at)).limit(200)
        res = await db.execute(stmt)
        rows = list(res.scalars().all())

    # Optional tag filter (JSONB) — do it in Python for portability
    if tags:
        wanted = set(tags)
        rows = [r for r in rows if r.tags and set(r.tags) & wanted]

    scored: list[ScoredMemory] = []
    for r in rows:
        base, reason = rank(r)
        # keyword-hit boost
        kw_hits = _keyword_hit(r.content, keywords)
        boost = kw_hits * 8.0
        # tag-hit boost
        if tags and r.tags:
            boost += len(set(tags) & set(r.tags)) * 4.0
        scored.append(ScoredMemory(
            memory=r, score=base + boost,
            reason=f"{reason} +kw={kw_hits}",
        ))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# TTL purge
# ---------------------------------------------------------------------------
async def purge_expired(db: AsyncSession) -> int:
    """Delete memories whose ttl_days has elapsed. Returns count deleted."""
    now = datetime.now(timezone.utc)
    res = await db.execute(select(CopilotMemory).where(CopilotMemory.ttl_days.isnot(None)))
    deleted = 0
    for m in res.scalars():
        if not m.created_at or not m.ttl_days:
            continue
        age_days = (now - m.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 86400.0
        if age_days > m.ttl_days:
            await db.delete(m)
            deleted += 1
    if deleted:
        await db.commit()
    return deleted


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
async def consolidate_from_trace(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID | None,
    trace_id: UUID,
    prompt: str | None,
    intent: str | None,
    output_text: str | None = None,
    status: str | None = None,
) -> CopilotMemory | None:
    """Heuristic auto-consolidation from a copilot trace → task_history memory.

    Rules (v1, pattern-based; will be replaced by LLM extraction later):
    - Skip if prompt is empty or intent is "unknown"/"chit_chat"
    - Only successful traces (status='completed' or None) get memorized
    - Emit a ``task_history`` entry with content = "{intent}: {prompt-snippet}"
    - Deduplicate via key = f"trace:{trace_id}"
    """
    if not prompt or not prompt.strip():
        return None
    if intent in (None, "unknown", "chit_chat", "greeting"):
        return None
    if status not in (None, "completed", "success"):
        return None

    snippet_val = prompt.strip()
    if len(snippet_val) > 200:
        snippet_val = snippet_val[:197] + "..."
    content = f"[{intent}] {snippet_val}"
    if output_text:
        tail = output_text.strip()
        if len(tail) > 200:
            tail = tail[:197] + "..."
        content = f"{content}\n→ {tail}"

    return await create_memory(
        db,
        org_id=org_id, user_id=user_id,
        kind="task_history",
        content=content,
        key=f"trace:{trace_id}",
        weight=40,   # task history is lower priority than explicit preferences
        ttl_days=90, # forget task history after 90 days
        source_trace_id=trace_id,
        meta={"intent": intent, "status": status},
    )


async def memory_stats(
    db: AsyncSession, *, org_id: UUID, user_id: UUID | None,
) -> dict[str, int]:
    """Return per-kind counts for the accessible memories."""
    stmt = select(CopilotMemory).where(CopilotMemory.org_id == org_id)
    if user_id is not None:
        stmt = stmt.where(
            or_(CopilotMemory.user_id == user_id, CopilotMemory.scope == "org")
        )
    res = await db.execute(stmt)
    out: dict[str, int] = {}
    for row in res.scalars():
        out[row.kind] = out.get(row.kind, 0) + 1
    return out
