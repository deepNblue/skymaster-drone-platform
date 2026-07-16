"""Prometheus metrics endpoint — v1.0 monitoring track.

Exports:
  - skymaster_http_requests_total{method, path, status}
  - skymaster_http_request_duration_seconds{method, path}
  - skymaster_missions_dispatched_total
  - skymaster_geofence_blocks_total{kind}
  - skymaster_uom_reports_total{status}
  - skymaster_ws_connections{channel}

Uses ``prometheus_client`` (bundled with fastapi/starlette middleware) or
falls back to a hand-rolled text-format exporter to avoid an extra dep.
"""
from __future__ import annotations

import threading
import time
from typing import Awaitable, Callable

from fastapi import APIRouter, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

router = APIRouter(tags=["metrics"])


# ---------------------------------------------------------------- collectors
class _Counter:
    def __init__(self, name: str, help_: str, labelnames: tuple[str, ...] = ()) -> None:
        self.name = name
        self.help = help_
        self.labelnames = labelnames
        self._data: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(labels.get(k, "") for k in self.labelnames)
        with self._lock:
            self._data[key] = self._data.get(key, 0.0) + amount

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self.name} {self.help}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            items = list(self._data.items())
        if not items:
            lines.append(f"{self.name} 0")
            return lines
        for key, val in items:
            if self.labelnames:
                label_str = ",".join(
                    f'{k}="{v}"' for k, v in zip(self.labelnames, key)
                )
                lines.append(f"{self.name}{{{label_str}}} {val}")
            else:
                lines.append(f"{self.name} {val}")
        return lines


class _Histogram:
    """Very simple histogram — track sum, count, and per-bucket counts."""

    _BUCKETS = (0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self, name: str, help_: str, labelnames: tuple[str, ...] = ()) -> None:
        self.name = name
        self.help = help_
        self.labelnames = labelnames
        self._sum: dict[tuple[str, ...], float] = {}
        self._count: dict[tuple[str, ...], int] = {}
        self._buckets: dict[tuple[str, ...], list[int]] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(labels.get(k, "") for k in self.labelnames)
        with self._lock:
            self._sum[key] = self._sum.get(key, 0.0) + value
            self._count[key] = self._count.get(key, 0) + 1
            buckets = self._buckets.setdefault(key, [0] * len(self._BUCKETS))
            for i, bound in enumerate(self._BUCKETS):
                if value <= bound:
                    buckets[i] += 1

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self.name} {self.help}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            keys = list(self._sum.keys())
        for key in keys:
            label_prefix = (
                ",".join(f'{k}="{v}"' for k, v in zip(self.labelnames, key))
                if self.labelnames else ""
            )
            for i, bound in enumerate(self._BUCKETS):
                extra = f'le="{bound}"'
                lbls = f"{label_prefix},{extra}" if label_prefix else extra
                lines.append(f"{self.name}_bucket{{{lbls}}} {self._buckets[key][i]}")
            extra_inf = 'le="+Inf"'
            lbls = f"{label_prefix},{extra_inf}" if label_prefix else extra_inf
            lines.append(f"{self.name}_bucket{{{lbls}}} {self._count[key]}")
            lbls_sc = f"{{{label_prefix}}}" if label_prefix else ""
            lines.append(f"{self.name}_sum{lbls_sc} {self._sum[key]}")
            lines.append(f"{self.name}_count{lbls_sc} {self._count[key]}")
        return lines


class _Gauge:
    def __init__(self, name: str, help_: str, labelnames: tuple[str, ...] = ()) -> None:
        self.name = name
        self.help = help_
        self.labelnames = labelnames
        self._data: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels: str) -> None:
        key = tuple(labels.get(k, "") for k in self.labelnames)
        with self._lock:
            self._data[key] = value

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(labels.get(k, "") for k in self.labelnames)
        with self._lock:
            self._data[key] = self._data.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self.inc(-amount, **labels)

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self.name} {self.help}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            items = list(self._data.items())
        if not items:
            lines.append(f"{self.name} 0")
            return lines
        for key, val in items:
            if self.labelnames:
                label_str = ",".join(
                    f'{k}="{v}"' for k, v in zip(self.labelnames, key)
                )
                lines.append(f"{self.name}{{{label_str}}} {val}")
            else:
                lines.append(f"{self.name} {val}")
        return lines


# ---------------------------------------------------------------- registry
HTTP_REQ_TOTAL = _Counter(
    "skymaster_http_requests_total",
    "Total HTTP requests processed",
    ("method", "path", "status"),
)
HTTP_REQ_DURATION = _Histogram(
    "skymaster_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ("method", "path"),
)
MISSIONS_DISPATCHED = _Counter(
    "skymaster_missions_dispatched_total",
    "Total missions dispatched to drones",
)
GEOFENCE_BLOCKS = _Counter(
    "skymaster_geofence_blocks_total",
    "Total mission dispatches blocked by geofence",
    ("kind",),
)
UOM_REPORTS = _Counter(
    "skymaster_uom_reports_total",
    "Flight reports submitted, grouped by terminal status",
    ("status",),
)
UOM_REJECTIONS = _Counter(
    "skymaster_uom_rejections_total",
    "UOM flight reports rejected — compliance signal for Grafana",
    ("reason",),
)
AUDIT_EVENTS = _Counter(
    "skymaster_audit_events_total",
    "Total audited actions logged by AuditMiddleware",
    ("actor_role", "method"),
)
WS_CONNECTIONS = _Gauge(
    "skymaster_ws_connections",
    "Currently open WebSocket connections",
    ("channel",),
)
WS_ACTIVE = _Gauge(
    "skymaster_ws_active_connections",
    "Total open WebSocket connections across all channels",
)

_ALL_COLLECTORS = [
    HTTP_REQ_TOTAL, HTTP_REQ_DURATION, MISSIONS_DISPATCHED,
    GEOFENCE_BLOCKS, UOM_REPORTS, UOM_REJECTIONS, AUDIT_EVENTS,
    WS_CONNECTIONS, WS_ACTIVE,
]


# ---------------------------------------------------------------- middleware
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            status = "500"
            raise
        finally:
            elapsed = time.perf_counter() - start
            # Aggregate by templated path if available, else raw path.
            path = request.url.path
            route = request.scope.get("route")
            if route is not None and getattr(route, "path", None):
                path = route.path
            HTTP_REQ_TOTAL.inc(
                method=request.method, path=path, status=status,
            )
            HTTP_REQ_DURATION.observe(
                elapsed, method=request.method, path=path,
            )
        return response


# ---------------------------------------------------------------- endpoint
@router.get("/metrics", response_class=Response)
async def metrics() -> Response:
    lines: list[str] = []
    for c in _ALL_COLLECTORS:
        lines.extend(c.render())
    body = "\n".join(lines) + "\n"
    return Response(content=body, media_type="text/plain; version=0.0.4")
