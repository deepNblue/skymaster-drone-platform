"""D2.4 · Annotation semantic search service.

Copilot Agent 二期功能 — 在场景标注库上做基于关键词 + 语义规则的
"AI 辅助标注检索". 不引入 embedding 模型 (保持轻量), 而是把中文关键
词、严重度别名、几何类型别名、图层别名做规则化归一化, 支持模糊查询.

调用场景 (来自 Copilot chat):
  用户: "把最近的所有裂缝找出来"
  agent 内部调用:
      search_annotations(scene_id=..., query="裂缝")
  服务层返回按相关度排序的标注列表, agent 引用它答复.

搜索维度:
  1. label ILIKE (SQL 层)
  2. description ILIKE
  3. 语义扩展: "裂缝" -> line kind + high/critical severity
     "淤积" / "面积" -> polygon
     "点位" / "缺陷点" -> point
     "紧急" / "危险" -> critical severity
     "紧急" / "high" 等映射
  4. 图层别名: "缺陷层"/"defect"/"缺陷" 归到 layer="defect"

相关度评分:
  label 命中 +3
  description 命中 +1
  几何/严重度语义扩展命中 +2
  分数排序 DESC, 同分按 created_at DESC.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scene_annotation import SceneAnnotation


# ---------------------------------------------------------------------------
# Semantic dictionaries — Chinese + English aliases.
# ---------------------------------------------------------------------------
GEOM_KIND_ALIASES: dict[str, list[str]] = {
    "point": [
        "点", "点位", "缺陷点", "打点", "point", "标点", "pin",
    ],
    "line": [
        "线", "裂缝", "断裂", "折线", "crack", "line",
        "polyline", "边线",
    ],
    "polygon": [
        "面", "区域", "淤积", "淤积区", "区块", "地块",
        "面积", "polygon", "range", "area",
    ],
    "volume": [
        "体", "体积", "空间体", "堆料", "volume", "堆积",
    ],
}

SEVERITY_ALIASES: dict[str, list[str]] = {
    "critical": ["紧急", "危险", "严重", "critical", "红色", "红警"],
    "high": ["高危", "高", "high", "橙色", "重点"],
    "medium": ["中", "中危", "medium", "黄色"],
    "low": ["低", "轻", "low", "蓝色"],
    "info": ["信息", "info", "备注"],
}

LAYER_ALIASES: dict[str, list[str]] = {
    "defect": ["缺陷", "缺陷层", "defect", "问题"],
    "sensor": ["传感器", "sensor", "监测点"],
    "note": ["备注", "note", "笔记"],
    "default": ["默认", "default"],
}


def _reverse_map(d: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Return [(alias, canonical), ...] sorted by longest alias first
    so multi-character Chinese phrases match before single character."""
    pairs: list[tuple[str, str]] = []
    for canon, aliases in d.items():
        for a in aliases:
            pairs.append((a, canon))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


_GEOM_REV = _reverse_map(GEOM_KIND_ALIASES)
_SEV_REV = _reverse_map(SEVERITY_ALIASES)
_LAY_REV = _reverse_map(LAYER_ALIASES)


def parse_query(q: str) -> dict[str, Any]:
    """Decompose a natural-language query into structured filters.

    Returns:
      {
        "raw": original,
        "keywords": [str, ...],       # for ILIKE
        "geom_kinds": {'line', ...},  # semantic-extended
        "severities": {'critical', ...},
        "layers": {'defect', ...},
      }
    """
    q0 = (q or "").strip()
    result: dict[str, Any] = {
        "raw": q0,
        "keywords": [],
        "geom_kinds": set(),
        "severities": set(),
        "layers": set(),
    }
    if not q0:
        return result

    lower = q0.lower()

    for alias, canon in _GEOM_REV:
        if alias.lower() in lower:
            result["geom_kinds"].add(canon)
    for alias, canon in _SEV_REV:
        if alias.lower() in lower:
            result["severities"].add(canon)
    for alias, canon in _LAY_REV:
        if alias.lower() in lower:
            result["layers"].add(canon)

    # keyword split (whitespace + punctuation)
    tokens = [t for t in re.split(r"[\s,;，。；:：]+", q0) if t]
    # keep tokens length >=1 that aren't just stopwords.
    _stop = {"的", "了", "和", "或", "with", "and", "or"}
    result["keywords"] = [t for t in tokens if t.lower() not in _stop]

    return result


async def search_annotations(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    scene_id: uuid.UUID,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Full-text-ish search over annotations for one scene.

    Returns a list of {annotation, score, matched_reasons} entries
    sorted by score DESC, created_at DESC.
    """
    parsed = parse_query(query)

    conds: list = [
        SceneAnnotation.org_id == org_id,
        SceneAnnotation.scene_id == scene_id,
    ]
    q_stmt = select(SceneAnnotation).where(*conds)

    # If we have at least one signal (keyword / semantic hint), narrow
    # the SQL to reduce over-fetch. Otherwise return latest N.
    if parsed["keywords"]:
        ilikes = []
        for kw in parsed["keywords"]:
            like = f"%{kw}%"
            ilikes.append(SceneAnnotation.label.ilike(like))
            ilikes.append(SceneAnnotation.description.ilike(like))
        semantic_or = []
        if parsed["geom_kinds"]:
            semantic_or.append(
                SceneAnnotation.geom_kind.in_(parsed["geom_kinds"]),
            )
        if parsed["severities"]:
            semantic_or.append(
                SceneAnnotation.severity.in_(parsed["severities"]),
            )
        if parsed["layers"]:
            semantic_or.append(
                SceneAnnotation.layer.in_(parsed["layers"]),
            )
        q_stmt = q_stmt.where(or_(*ilikes, *semantic_or))
    else:
        # Semantic-only query, no free-text keywords.
        semantic_or = []
        if parsed["geom_kinds"]:
            semantic_or.append(
                SceneAnnotation.geom_kind.in_(parsed["geom_kinds"]),
            )
        if parsed["severities"]:
            semantic_or.append(
                SceneAnnotation.severity.in_(parsed["severities"]),
            )
        if parsed["layers"]:
            semantic_or.append(
                SceneAnnotation.layer.in_(parsed["layers"]),
            )
        if semantic_or:
            q_stmt = q_stmt.where(or_(*semantic_or))
        # If no filter at all, just latest N (caller asked for empty
        # query — recent annotations).

    q_stmt = q_stmt.order_by(SceneAnnotation.created_at.desc()).limit(200)
    rows = list((await db.execute(q_stmt)).scalars().all())

    # In-Python scoring — cheaper than SQL ranking for our N.
    scored: list[dict[str, Any]] = []
    for r in rows:
        score = 0
        reasons: list[str] = []
        lbl = (r.label or "").lower()
        desc = (r.description or "").lower()
        for kw in parsed["keywords"]:
            k = kw.lower()
            if k in lbl:
                score += 3
                reasons.append(f"label 命中 '{kw}'")
            if k in desc:
                score += 1
                reasons.append(f"描述命中 '{kw}'")
        if r.geom_kind in parsed["geom_kinds"]:
            score += 2
            reasons.append(f"几何类型={r.geom_kind}")
        if r.severity in parsed["severities"]:
            score += 2
            reasons.append(f"严重度={r.severity}")
        if r.layer in parsed["layers"]:
            score += 2
            reasons.append(f"图层={r.layer}")

        if score > 0 or not any([
            parsed["keywords"], parsed["geom_kinds"],
            parsed["severities"], parsed["layers"],
        ]):
            scored.append({
                "annotation": r,
                "score": score,
                "matched_reasons": reasons,
            })

    scored.sort(
        key=lambda x: (
            -x["score"],
            -x["annotation"].created_at.timestamp()
            if x["annotation"].created_at else 0,
        ),
    )
    return scored[:limit]


def suggest_annotation_from_query(
    query: str,
) -> dict[str, Any] | None:
    """Given a natural-language user query, propose a sensible
    default annotation template.

    Purely a convenience for the Copilot Agent — no I/O.
    Returns None if the query is empty.
    """
    parsed = parse_query(query)
    if not parsed["raw"]:
        return None

    kind = next(iter(parsed["geom_kinds"]), "point")
    severity = next(iter(parsed["severities"]), "medium")
    layer = next(iter(parsed["layers"]), "default")
    # Pick label = first non-empty keyword, fallback to raw truncated.
    label = None
    for kw in parsed["keywords"]:
        # Skip trivial semantic tokens themselves.
        if kw.lower() not in {
            *(a for _, aliases in GEOM_KIND_ALIASES.items()
              for a in aliases),
            *(a for _, aliases in SEVERITY_ALIASES.items()
              for a in aliases),
            *(a for _, aliases in LAYER_ALIASES.items()
              for a in aliases),
        }:
            label = kw
            break
    if not label:
        label = parsed["raw"][:60]

    return {
        "geom_kind": kind,
        "severity": severity,
        "layer": layer,
        "label": label,
    }
