"""MediaMTX-backed video stream manager.

Wraps the MediaMTX HTTP control API (default :9997) so we can:
  * Register/unregister per-drone paths that pull an RTSP source from
    the drone video downlink.
  * Expose a stable HLS playback URL to the frontend.
  * Proxy a JPEG snapshot from MediaMTX.
  * List active paths for admin/debug UIs.

All I/O is async via `httpx.AsyncClient`.  Every call has a bounded
timeout and a small retry loop so a transient MediaMTX restart doesn't
poison the API layer.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_S = 0.25


def _path_name(drone_id: UUID | str) -> str:
    """Deterministic mediamtx path name for a given drone."""
    return f"drone-{drone_id}"


class StreamManagerError(RuntimeError):
    """Raised when the mediamtx control plane rejects or is unreachable."""


class StreamManager:
    """Thin async client for the MediaMTX v3 control API.

    Parameters
    ----------
    api_url:
        Base URL of the mediamtx HTTP API (e.g. ``http://mediamtx:9997``).
    hls_base:
        Public base URL used to build HLS playback links returned to the
        frontend (e.g. ``http://mediamtx:8888``).
    rtsp_base:
        Public base URL used to build RTSP playback links.
    client:
        Optional pre-built ``httpx.AsyncClient`` (useful for tests /
        MockTransport).  When omitted, one is created lazily and closed
        via :meth:`aclose`.
    """

    def __init__(
        self,
        api_url: str | None = None,
        hls_base: str | None = None,
        rtsp_base: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_url = (api_url or settings.mediamtx_api_url).rstrip("/")
        self.hls_base = (hls_base or settings.mediamtx_hls_url_base).rstrip("/")
        self.rtsp_base = (
            rtsp_base or settings.mediamtx_rtsp_url_base
        ).rstrip("/")
        self._client = client
        self._owns_client = client is None

    # ------------------------------------------------------------------ #
    # HTTP plumbing                                                      #
    # ------------------------------------------------------------------ #
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        return self._client

    async def aclose(self) -> None:
        """Release the underlying httpx client (only if we created it)."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> Any:
        """Call the mediamtx API with retries + timeout.

        A 404 is *not* retried (path missing is a permanent state).
        Connection errors and 5xx are retried up to ``_MAX_ATTEMPTS``.
        """
        client = await self._get_client()
        url = f"{self.api_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await client.request(method, url, json=json)
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                log.warning(
                    "mediamtx %s %s failed (attempt %d/%d): %s",
                    method,
                    path,
                    attempt,
                    _MAX_ATTEMPTS,
                    exc,
                )
                if attempt == _MAX_ATTEMPTS:
                    break
                await asyncio.sleep(_RETRY_BACKOFF_S * attempt)
                continue

            if resp.status_code >= 500 and attempt < _MAX_ATTEMPTS:
                log.warning(
                    "mediamtx %s %s -> %s (retrying)",
                    method,
                    path,
                    resp.status_code,
                )
                await asyncio.sleep(_RETRY_BACKOFF_S * attempt)
                continue

            if resp.status_code >= 400:
                raise StreamManagerError(
                    f"mediamtx {method} {path} failed: "
                    f"{resp.status_code} {resp.text}"
                )

            if not expect_json or not resp.content:
                return None
            try:
                return resp.json()
            except ValueError:
                return None

        raise StreamManagerError(
            f"mediamtx {method} {path} unreachable: {last_exc!r}"
        )

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #
    async def register_stream(
        self, drone_id: UUID | str, source_url: str
    ) -> dict[str, Any]:
        """Create a mediamtx path that pulls ``source_url`` on demand.

        Uses MediaMTX v3: ``POST /v3/config/paths/add/{name}`` with a
        JSON body containing at least ``{"source": ...}``.
        """
        name = _path_name(drone_id)
        body = {
            "source": source_url,
            "sourceOnDemand": False,
        }
        await self._request(
            "POST",
            f"/v3/config/paths/add/{name}",
            json=body,
            expect_json=False,
        )
        return {
            "drone_id": str(drone_id),
            "name": name,
            "hls_url": self.get_hls_url(drone_id),
            "rtsp_url": self.get_rtsp_url(drone_id),
            "active": True,
            "source_url": source_url,
        }

    async def unregister_stream(self, drone_id: UUID | str) -> None:
        """Remove the mediamtx path for a given drone."""
        name = _path_name(drone_id)
        await self._request(
            "DELETE",
            f"/v3/config/paths/delete/{name}",
            expect_json=False,
        )

    def get_hls_url(self, drone_id: UUID | str) -> str:
        """Public HLS playback URL served by mediamtx on :8888."""
        return f"{self.hls_base}/{_path_name(drone_id)}/index.m3u8"

    def get_rtsp_url(self, drone_id: UUID | str) -> str:
        """Public RTSP playback URL served by mediamtx on :8554."""
        return f"{self.rtsp_base}/{_path_name(drone_id)}"

    async def get_snapshot(self, drone_id: UUID | str) -> bytes:
        """Proxy the current keyframe from mediamtx as JPEG bytes.

        MediaMTX exposes JPEG snapshots off the HLS muxer at
        ``/{name}/snapshot`` on the HLS port.
        """
        client = await self._get_client()
        url = f"{self.hls_base}/{_path_name(drone_id)}/snapshot"
        try:
            resp = await client.get(url)
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            raise StreamManagerError(
                f"mediamtx snapshot unreachable: {exc!r}"
            ) from exc
        if resp.status_code >= 400:
            raise StreamManagerError(
                f"mediamtx snapshot failed: {resp.status_code}"
            )
        return resp.content

    async def list_active_streams(self) -> list[dict[str, Any]]:
        """List active mediamtx paths (v3: ``GET /v3/paths/list``)."""
        payload = await self._request("GET", "/v3/paths/list")
        if not isinstance(payload, dict):
            return []
        items = payload.get("items") or []
        results: list[dict[str, Any]] = []
        for item in items:
            name = item.get("name", "")
            drone_id: str | None = None
            if name.startswith("drone-"):
                drone_id = name[len("drone-") :]
            results.append(
                {
                    "name": name,
                    "drone_id": drone_id,
                    "ready": bool(item.get("ready")),
                    "source": item.get("source"),
                    "tracks": item.get("tracks", []),
                    "hls_url": (
                        f"{self.hls_base}/{name}/index.m3u8" if name else None
                    ),
                    "rtsp_url": (
                        f"{self.rtsp_base}/{name}" if name else None
                    ),
                }
            )
        return results


# --- Module-level singleton --------------------------------------------------

_manager: StreamManager | None = None


def get_stream_manager() -> StreamManager:
    """Return the process-wide :class:`StreamManager` singleton."""
    global _manager
    if _manager is None:
        _manager = StreamManager()
    return _manager


__all__ = ["StreamManager", "StreamManagerError", "get_stream_manager"]
