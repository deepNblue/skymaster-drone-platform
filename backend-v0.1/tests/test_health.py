"""Smoke tests for the /api/v1/health endpoint.

These tests do NOT require a real database or redis to be running:
the endpoint catches connection errors and reports a "degraded" status.
"""
from __future__ import annotations

from httpx import AsyncClient


async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /api/v1/health always returns HTTP 200 (ok or degraded)."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200


async def test_health_shape(client: AsyncClient) -> None:
    """Response JSON must contain a 'status' key."""
    resp = await client.get("/api/v1/health")
    body = resp.json()
    assert "status" in body
    assert body["status"] in {"ok", "degraded"}
