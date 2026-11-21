"""Tests for the 12309 scenario aggregation layer."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.main import app
from app.services.scenario_12309 import (
    Scenario12309Service,
    _in_bbox,
    _polygon_touches_bbox,
)


class _Result:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeDB:
    async def execute(self, stmt):
        return _Result()


class _User:
    id = uuid4()
    org_id = uuid4()


@pytest.fixture
def client():
    old_user = app.dependency_overrides.get(get_current_user)
    old_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_current_user] = lambda: _User()
    app.dependency_overrides[get_db] = lambda: _FakeDB()
    if hasattr(app.state, "dji_connector"):
        del app.state.dji_connector
    try:
        yield TestClient(app)
    finally:
        if old_user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = old_user
        if old_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old_db


def test_config_meta_and_kpis():
    svc = Scenario12309Service()
    meta = svc.meta()
    assert meta["id"] == "12309"
    assert meta["config_loaded"] is True
    assert meta["region"]["alt_limit_m"] == 150
    assert [k["key"] for k in meta["kpis"]] == [
        "fleet_online", "active_missions", "open_alerts",
        "pending_approvals", "live_streams", "evidence_count",
    ]


def test_severity_rules_are_config_driven():
    svc = Scenario12309Service()
    assert svc.severity(0.92)["level"] == "high"
    assert svc.severity(0.7)["level"] == "medium"
    assert svc.severity(0.2)["level"] == "low"
    assert svc.severity(None)["level"] == "low"


def test_geo_helpers():
    bbox = [108.15, 22.55, 108.50, 22.95]
    assert _in_bbox(22.8167, 108.3167, bbox)
    assert not _in_bbox(23.5, 108.3, bbox)
    assert _in_bbox(None, None, bbox)  # missing coordinates are kept
    assert _polygon_touches_bbox([[108.3, 22.8], [108.4, 22.9]], bbox)
    assert not _polygon_touches_bbox([[109.0, 23.5]], bbox)
    assert _polygon_touches_bbox(None, bbox)


def test_routes_filter_to_12309():
    routes = Scenario12309Service()._routes()
    assert routes["available"] is True
    assert routes["count"] == 3
    assert all(r["id"].startswith("nanning-12309-") for r in routes["items"])


def test_custom_config_override(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text('{"id":"test","short_name":"T","scope":{"route_id_prefix":"zzz-"},'
                    '"severity_rules":[{"min_confidence":0.5,"level":"high","label":"高"}]}',
                    encoding="utf-8")
    svc = Scenario12309Service(config_path=str(path))
    assert svc.meta()["id"] == "test"
    assert svc.severity(0.9)["label"] == "高"
    assert svc._routes()["count"] == 0


@pytest.mark.asyncio
async def test_overview_degrades_without_connector_or_streams():
    svc = Scenario12309Service(connector=None)
    report = await svc.overview(_FakeDB(), _User())
    assert report["meta"]["id"] == "12309"
    assert report["routes"]["count"] == 3
    assert report["missions"]["available"] is False
    assert "连接器" in report["missions"]["reason"]
    for key in ("fleet", "alerts", "approvals", "evidence", "streams"):
        assert report[key]["available"] in (True, False)
        assert isinstance(report[key]["items"], list)
    assert set(report["kpi"]) == {
        "fleet_online", "active_missions", "open_alerts",
        "pending_approvals", "live_streams", "evidence_count",
    }
    assert isinstance(report["timeline"], list)


def test_kpi_and_timeline_assembly():
    svc = Scenario12309Service()
    results = {
        "fleet": {"items": [{"status": "online"}, {"status": "offline"}]},
        "missions": {"items": [{"state": "running"}, {"state": "success"}]},
        "alerts": {"items": [{"open": True}, {"open": False}]},
        "approvals": {"items": [{"open": True}, {"open": True}]},
        "streams": {"count": 2},
        "evidence": {"count": 3},
    }
    kpi = svc._kpi(results)
    assert kpi["fleet_online"] == 1
    assert kpi["active_missions"] == 1
    assert kpi["open_alerts"] == 1
    assert kpi["pending_approvals"] == 2
    assert kpi["live_streams"] == 2
    assert kpi["evidence_count"] == 3

    results["timeline"] = None
    results["alerts"]["items"][0]["created_at"] = "2026-11-21T01:00:00+00:00"
    results["approvals"]["items"] = [{
        "id": "a1", "title": "审批单", "status": "submitted",
        "created_at": "2026-11-21T03:00:00+00:00",
    }]
    timeline = svc._timeline(results)
    assert timeline[0]["kind"] == "approval"
    assert timeline[1]["kind"] == "alert"


def test_api_list_scenarios(client):
    r = client.get("/api/v1/scenarios")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1
    assert any(i["id"] == "12309" for i in data["items"])


def test_api_overview(client):
    r = client.get("/api/v1/scenarios/12309/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["meta"]["short_name"] == "12309 防控"
    assert data["routes"]["count"] == 3
    assert data["missions"]["available"] is False
    assert data["generated_at"]
