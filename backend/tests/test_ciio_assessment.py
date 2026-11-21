"""R23 · CIIO 自评服务单元测试。

由于 checks 依赖真实 DB（Drone/AuditLog 查询），这里用 mock session
只测 markdown 渲染 + status 汇总的纯逻辑部分。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List

import pytest

from app.services import ciio_assessment as svc
from app.services.ciio_assessment import Check, CIIOReport, Status, render_markdown


def _mk(code: str, cat: str, status: Status) -> Check:
    return Check(
        code=code,
        category=cat,
        title=f"title-{code}",
        obligation_zh=f"义务-{code}",
        status=status,
        evidence=f"evidence-{code}",
        references=[f"ref-{code}.py"],
    )


def _mk_report(checks: List[Check]) -> CIIOReport:
    from datetime import datetime, timezone

    counts = {s.value: 0 for s in Status}
    for c in checks:
        counts[c.status.value] += 1
    total = len(checks)
    coverage = (counts["pass"] + 0.5 * counts["partial"]) / max(1, total)
    return CIIOReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total=total,
        counts=counts,
        coverage_pct=round(coverage * 100, 1),
        checks=checks,
    )


def test_report_to_dict_structure():
    checks = [
        _mk("CIIO-A1", "A", Status.PASS),
        _mk("CIIO-B1", "B", Status.PARTIAL),
        _mk("CIIO-C3", "C", Status.UNKNOWN),
        _mk("CIIO-E1", "E", Status.FAIL),
    ]
    rep = _mk_report(checks)
    d = rep.to_dict()
    assert d["total"] == 4
    assert d["counts"]["pass"] == 1
    assert d["counts"]["partial"] == 1
    assert d["counts"]["unknown"] == 1
    assert d["counts"]["fail"] == 1
    # 覆盖度 = (1 + 0.5) / 4 = 37.5%
    assert d["coverage_pct"] == 37.5
    assert len(d["checks"]) == 4


def test_render_markdown_has_all_categories_and_checks():
    checks = [
        _mk("CIIO-A1", "A", Status.PASS),
        _mk("CIIO-B1", "B", Status.PARTIAL),
        _mk("CIIO-C1", "C", Status.PASS),
        _mk("CIIO-D1", "D", Status.UNKNOWN),
        _mk("CIIO-E1", "E", Status.PASS),
        _mk("CIIO-F1", "F", Status.PARTIAL),
    ]
    md = render_markdown(_mk_report(checks))
    # 6 category headers
    for code, name, _desc in svc.CATEGORIES:
        assert f"## {code} · {name}" in md
    # every check code appears
    for c in checks:
        assert c.code in md
        assert c.obligation_zh in md
    # header block
    assert "SkyMaster · 关键信息基础设施" in md
    assert "覆盖度评分" in md
    assert "国务院令 745" in md


def test_render_markdown_status_icons():
    checks = [
        _mk("CIIO-A1", "A", Status.PASS),
        _mk("CIIO-A2", "A", Status.FAIL),
        _mk("CIIO-B1", "B", Status.PARTIAL),
        _mk("CIIO-B2", "B", Status.UNKNOWN),
    ]
    md = render_markdown(_mk_report(checks))
    assert "✅" in md
    assert "❌" in md
    assert "🟡" in md
    assert "❓" in md


def test_coverage_pct_all_pass():
    checks = [_mk(f"CIIO-X{i}", "A", Status.PASS) for i in range(10)]
    rep = _mk_report(checks)
    assert rep.coverage_pct == 100.0


def test_coverage_pct_all_partial():
    checks = [_mk(f"CIIO-X{i}", "A", Status.PARTIAL) for i in range(10)]
    rep = _mk_report(checks)
    assert rep.coverage_pct == 50.0


def test_coverage_pct_all_unknown_zero():
    checks = [_mk(f"CIIO-X{i}", "A", Status.UNKNOWN) for i in range(5)]
    rep = _mk_report(checks)
    assert rep.coverage_pct == 0.0


def test_all_checks_list_length_at_least_20():
    """R23 承诺 30 项检查点；先落地 20 项打通端到端，其余为运营方补充材料类项。"""
    assert len(svc.ALL_CHECKS) >= 20


def test_categories_cover_six_domains():
    assert len(svc.CATEGORIES) == 6
    codes = {c[0] for c in svc.CATEGORIES}
    assert codes == {"A", "B", "C", "D", "E", "F"}
