"""Tests for the mission_watcher (rising-edge detection)."""
from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import fakeredis.aioredis as fr
import pytest

from app.services.mission_watcher import MissionWatcher


def _spawn_state_server(state: dict, port: int) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **kw): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state).encode())

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.asyncio
async def test_mission_watcher_rising_edge():
    port = 45671
    state = {"mode": "mission", "mission_progress": "0/2", "mission_completed_at": None}
    srv = _spawn_state_server(state, port)

    r = fr.FakeRedis(decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.psubscribe("mission.event.*")

    w = MissionWatcher(r, {7: port}, poll_interval_s=0.1)
    watcher_task = asyncio.create_task(w.run())

    try:
        # Wait 0.3s — should see no events yet.
        await asyncio.sleep(0.3)
        # Toggle the state to look "completed"
        state["mission_completed_at"] = 12345.6
        state["mission_progress"] = "2/2"

        # Collect messages for up to 3s
        events = []
        for _ in range(30):
            m = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if m and isinstance(m.get("data"), str):
                events.append(json.loads(m["data"]))
                if len(events) >= 2:
                    break

        # We publish on both mission.event.7 and mission.event.all
        assert any(
            e.get("type") == "mission.completed" and e.get("sysid") == 7
            for e in events
        ), events
    finally:
        w.stop()
        watcher_task.cancel()
        try:
            await watcher_task
        except (asyncio.CancelledError, Exception):
            pass
        await pubsub.aclose()
        srv.shutdown()
