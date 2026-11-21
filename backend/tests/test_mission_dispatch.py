"""Tests for app.services.mission_dispatcher.MissionDispatcher."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from app.services.mission_dispatcher import (
    MAV_CMD_MISSION_START,
    MAV_CMD_NAV_RETURN_TO_LAUNCH,
    MAV_MISSION_ACCEPTED,
    MissionDispatcher,
)


def _mission(waypoints):
    """Lightweight stub for a Mission model — dispatcher only reads .waypoints."""
    return SimpleNamespace(waypoints=waypoints)


@pytest.mark.asyncio
async def test_validate_rejects_empty_waypoints():
    dispatcher = MissionDispatcher()
    result = await dispatcher.validate_mission(_mission([]))
    assert result.ok is False
    assert any("no waypoints" in e for e in result.errors)


@pytest.mark.asyncio
async def test_validate_rejects_invalid_coords():
    dispatcher = MissionDispatcher()
    mission = _mission([{"lat": 200.0, "lng": 10.0, "alt": 50.0}])
    result = await dispatcher.validate_mission(mission)
    assert result.ok is False
    assert any("lat" in e and "out of range" in e for e in result.errors)


@pytest.mark.asyncio
async def test_validate_accepts_good_mission():
    dispatcher = MissionDispatcher()
    mission = _mission(
        [
            {"lat": 39.9042, "lng": 116.4074, "alt": 50.0},
            {"lat": 39.9050, "lng": 116.4080, "alt": 60.0},
        ]
    )
    result = await dispatcher.validate_mission(mission)
    assert result.ok is True
    assert result.errors == []


@pytest.mark.asyncio
async def test_dispatch_calls_mission_upload_sequence():
    waypoints = [
        {"lat": 39.9042, "lng": 116.4074, "alt": 50.0},
        {"lat": 39.9050, "lng": 116.4080, "alt": 60.0},
    ]
    mission = _mission(waypoints)

    connector = MagicMock()
    # Track ordering across .mav.* calls via a parent mock.
    parent = MagicMock()
    parent.attach_mock(connector.mav.mission_count_send, "mission_count_send")
    parent.attach_mock(connector.mav.mission_item_int_send, "mission_item_int_send")
    parent.attach_mock(connector.mav.command_long_send, "command_long_send")

    # recv_match yields two MISSION_REQUESTs (one per waypoint) then a MISSION_ACK.
    req0 = SimpleNamespace(seq=0)
    req1 = SimpleNamespace(seq=1)
    ack = SimpleNamespace(type=MAV_MISSION_ACCEPTED)
    connector.recv_match.side_effect = [req0, req1, ack]

    dispatcher = MissionDispatcher(upload_timeout_s=1.0)
    result = await dispatcher.dispatch_to_drone(mission, connector)

    assert result["status"] == "dispatched"
    assert result["mavlink_ack"] == "MAV_MISSION_ACCEPTED"

    # mission_count sent exactly once with correct waypoint count.
    connector.mav.mission_count_send.assert_called_once()
    count_args = connector.mav.mission_count_send.call_args.args
    assert count_args[2] == len(waypoints)

    # mission_item_int sent once per waypoint.
    assert connector.mav.mission_item_int_send.call_count == len(waypoints)

    # command_long called for MISSION_START.
    connector.mav.command_long_send.assert_called_once()
    cmd_args = connector.mav.command_long_send.call_args.args
    assert cmd_args[2] == MAV_CMD_MISSION_START

    # Verify ordering: count → item_int (xN) → command_long (MISSION_START).
    ordered_names = [c[0] for c in parent.mock_calls]
    assert ordered_names == [
        "mission_count_send",
        "mission_item_int_send",
        "mission_item_int_send",
        "command_long_send",
    ]


@pytest.mark.asyncio
async def test_abort_sends_rtl():
    connector = MagicMock()
    dispatcher = MissionDispatcher()

    result = await dispatcher.abort(connector)

    assert result["status"] == "aborted"
    assert result["error"] is None

    connector.mav.command_long_send.assert_called_once()
    args = connector.mav.command_long_send.call_args.args
    # command_long_send(target_sys, target_comp, command, confirmation, p1..p7)
    assert args[2] == MAV_CMD_NAV_RETURN_TO_LAUNCH
