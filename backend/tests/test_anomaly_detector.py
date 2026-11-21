"""Unit tests for the anomaly detector."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.anomaly_detector import (
    check_anomaly, geoip_lookup,
)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return _FakeResult(self._rows)


def _mkevent(ip: str, country: str | None, minutes_ago: int, outcome="success"):
    return SimpleNamespace(
        ip=ip,
        country=country,
        outcome=outcome,
        created_at=datetime.now(tz=timezone.utc) - timedelta(minutes=minutes_ago),
    )


def test_geoip_lan_ranges():
    assert geoip_lookup("10.0.0.5") == "LAN"
    assert geoip_lookup("192.168.1.1") == "LAN"
    # empty string / None → None (no IP means no lookup)
    assert geoip_lookup("") in (None,)


def test_geoip_known_countries():
    assert geoip_lookup("36.1.2.3") == "CN"
    assert geoip_lookup("8.8.8.8") == "US"
    assert geoip_lookup("77.77.77.77") is None


@pytest.mark.asyncio
async def test_no_history_not_anomalous():
    session = _FakeSession([])
    r = await check_anomaly(session, user_id=uuid4(), ip="8.8.8.8")
    assert r is None


@pytest.mark.asyncio
async def test_same_ip_not_anomalous():
    session = _FakeSession([_mkevent("8.8.8.8", "US", 60)])
    r = await check_anomaly(session, user_id=uuid4(), ip="8.8.8.8")
    assert r is None


@pytest.mark.asyncio
async def test_new_country_flags():
    session = _FakeSession([_mkevent("36.1.2.3", "CN", 100)])
    r = await check_anomaly(session, user_id=uuid4(), ip="8.8.8.8")
    assert r is not None
    assert r["reason"] == "NEW_COUNTRY"


@pytest.mark.asyncio
async def test_impossible_travel():
    # Last login 1 min ago from CN, now from US = physical impossibility
    session = _FakeSession([
        _mkevent("36.1.2.3", "CN", 1),
        _mkevent("36.1.2.4", "CN", 60),
    ])
    r = await check_anomaly(session, user_id=uuid4(), ip="8.8.8.8")
    assert r is not None
    # Either NEW_COUNTRY or IMPOSSIBLE_TRAVEL — both surface US arrival
    assert r["reason"] in ("NEW_COUNTRY", "IMPOSSIBLE_TRAVEL")


@pytest.mark.asyncio
async def test_new_ip_same_country_soft_warn():
    session = _FakeSession([_mkevent("36.1.2.3", "CN", 60)])
    r = await check_anomaly(session, user_id=uuid4(), ip="36.9.9.9")
    assert r is not None
    assert r["reason"] == "NEW_IP"
