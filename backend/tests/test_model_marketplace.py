"""Test Model Marketplace endpoints (v2.2 E5)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_list_public_models(auth_client: AsyncClient) -> None:
    """Public listing endpoint returns published models."""
    response = await auth_client.get("/api/v1/model-marketplace/models?page=1&size=10")
    # Listing is public, doesn't require auth
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data


async def test_create_model_requires_auth(auth_client: AsyncClient) -> None:
    """Creating a model requires authenticated user."""
    response = await auth_client.post(
        "/api/v1/model-marketplace/models",
        json={
            "name": "test-model",
            "description": "this is a test model",
            "category": "detect",
            "license_type": "free",
        },
    )
    assert response.status_code == 401


async def test_filter_by_category(auth_client: AsyncClient) -> None:
    """Can filter models by category."""
    response = await auth_client.get(
        "/api/v1/model-marketplace/models?category=detect&page=1&size=10"
    )
    assert response.status_code == 200
    data = response.json()
    # Empty list is still success
    assert isinstance(data["items"], list)
