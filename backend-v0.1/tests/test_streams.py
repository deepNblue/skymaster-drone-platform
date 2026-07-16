"""Unit tests for :mod:`app.services.stream_manager`.

We don't hit a real MediaMTX instance — instead we route the
:class:`httpx.AsyncClient` through a :class:`httpx.MockTransport` and
assert on the outgoing requests and the response shaping done by
:class:`StreamManager`.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid4

import httpx
import pytest

from app.services.stream_manager import (
    StreamManager,
    StreamManagerError,
    _path_name,
)


API_URL = "http://mediamtx-test:9997"
HLS_BASE = "http://mediamtx-test:8888"
RTSP_BASE = "rtsp://mediamtx-test:8554"


def _make_manager(handler) -> StreamManager:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return StreamManager(
        api_url=API_URL,
        hls_base=HLS_BASE,
        rtsp_base=RTSP_BASE,
        client=client,
    )


# ---------------------------------------------------------------------- #
# register_stream                                                        #
# ---------------------------------------------------------------------- #
async def test_register_stream_calls_mediamtx_add_path() -> None:
    drone_id = uuid4()
    source_url = "rtsp://drone.local:8554/live"
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content or b"{}")
        return httpx.Response(200, json={})

    manager = _make_manager(handler)
    try:
        info = await manager.register_stream(drone_id, source_url)
    finally:
        await manager._client.aclose()  # type: ignore[union-attr]

    assert captured["method"] == "POST"
    assert captured["url"] == (
        f"{API_URL}/v3/config/paths/add/{_path_name(drone_id)}"
    )
    assert captured["body"]["source"] == source_url

    assert info["name"] == f"drone-{drone_id}"
    assert info["active"] is True
    assert info["source_url"] == source_url
    assert info["hls_url"] == (
        f"{HLS_BASE}/drone-{drone_id}/index.m3u8"
    )
    assert info["rtsp_url"] == f"{RTSP_BASE}/drone-{drone_id}"


async def test_register_stream_raises_on_400() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad path name")

    manager = _make_manager(handler)
    try:
        with pytest.raises(StreamManagerError):
            await manager.register_stream(uuid4(), "rtsp://x")
    finally:
        await manager._client.aclose()  # type: ignore[union-attr]


# ---------------------------------------------------------------------- #
# unregister_stream                                                      #
# ---------------------------------------------------------------------- #
async def test_unregister_stream_sends_delete() -> None:
    drone_id = uuid4()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200)

    manager = _make_manager(handler)
    try:
        await manager.unregister_stream(drone_id)
    finally:
        await manager._client.aclose()  # type: ignore[union-attr]

    assert captured["method"] == "DELETE"
    assert captured["url"] == (
        f"{API_URL}/v3/config/paths/delete/drone-{drone_id}"
    )


# ---------------------------------------------------------------------- #
# URL helpers                                                            #
# ---------------------------------------------------------------------- #
def test_hls_url_format() -> None:
    manager = StreamManager(
        api_url=API_URL, hls_base=HLS_BASE, rtsp_base=RTSP_BASE,
    )
    drone_id = UUID("00000000-0000-0000-0000-000000000001")
    assert manager.get_hls_url(drone_id) == (
        "http://mediamtx-test:8888/drone-"
        "00000000-0000-0000-0000-000000000001/index.m3u8"
    )
    assert manager.get_rtsp_url(drone_id) == (
        "rtsp://mediamtx-test:8554/drone-"
        "00000000-0000-0000-0000-000000000001"
    )


def test_hls_url_strips_trailing_slash() -> None:
    manager = StreamManager(
        api_url=API_URL + "/",
        hls_base=HLS_BASE + "/",
        rtsp_base=RTSP_BASE + "/",
    )
    assert manager.api_url == API_URL
    assert manager.hls_base == HLS_BASE
    assert manager.rtsp_base == RTSP_BASE


# ---------------------------------------------------------------------- #
# list_active_streams                                                    #
# ---------------------------------------------------------------------- #
async def test_list_active_streams_shapes_items() -> None:
    drone_id = uuid4()
    fake_response = {
        "items": [
            {
                "name": f"drone-{drone_id}",
                "ready": True,
                "source": {"type": "rtspSource"},
                "tracks": ["video"],
            },
            {
                "name": "unrelated",
                "ready": False,
                "source": None,
                "tracks": [],
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == f"{API_URL}/v3/paths/list"
        return httpx.Response(200, json=fake_response)

    manager = _make_manager(handler)
    try:
        items = await manager.list_active_streams()
    finally:
        await manager._client.aclose()  # type: ignore[union-attr]

    assert len(items) == 2
    first = items[0]
    assert first["name"] == f"drone-{drone_id}"
    assert first["drone_id"] == str(drone_id)
    assert first["ready"] is True
    assert first["hls_url"].endswith(f"drone-{drone_id}/index.m3u8")

    second = items[1]
    assert second["drone_id"] is None  # non-drone paths not classified


# ---------------------------------------------------------------------- #
# get_snapshot                                                           #
# ---------------------------------------------------------------------- #
async def test_get_snapshot_returns_bytes() -> None:
    drone_id = uuid4()
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == f"{HLS_BASE}/drone-{drone_id}/snapshot"
        return httpx.Response(200, content=jpeg)

    manager = _make_manager(handler)
    try:
        data = await manager.get_snapshot(drone_id)
    finally:
        await manager._client.aclose()  # type: ignore[union-attr]

    assert data == jpeg


async def test_get_snapshot_raises_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    manager = _make_manager(handler)
    try:
        with pytest.raises(StreamManagerError):
            await manager.get_snapshot(uuid4())
    finally:
        await manager._client.aclose()  # type: ignore[union-attr]


# ---------------------------------------------------------------------- #
# Retry behavior                                                         #
# ---------------------------------------------------------------------- #
async def test_request_retries_on_5xx_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 2:
            return httpx.Response(503, text="starting up")
        return httpx.Response(200, json={"items": []})

    manager = _make_manager(handler)
    try:
        items = await manager.list_active_streams()
    finally:
        await manager._client.aclose()  # type: ignore[union-attr]

    assert items == []
    assert len(calls) == 2  # one retry
