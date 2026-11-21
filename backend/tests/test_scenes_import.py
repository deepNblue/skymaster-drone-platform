"""Test for mission → 3DGS import endpoint (E3.4)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.main import app
from app.models.mission import Mission
from app.models.media_asset import MediaAsset
from app.models.user import User
from app.models.organization import Organization
from app.db import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


async def test_import_mission_creates_scene_with_assets():
    """Happy path: import completed mission with images creates scene with all assets."""
    # Arrange: create org, user, mission, some media assets
    async with AsyncSessionLocal() as session:
        org = Organization(name="Test Org")
        session.add(org)
        await session.flush()
        org_id = org.id

        user = User(email="test@example.com", org_id=org_id, role="system_officer")
        session.add(user)
        await session.flush()
        user_id = user.id

        mission = Mission(
            id=None,
            org_id=org_id,
            name="Test Import Mission",
            status="completed",
            created_by=user_id,
        )
        session.add(mission)
        await session.flush()
        mission_id = mission.id

        # Add two image assets
        for i in range(2):
            ma = MediaAsset(
                mission_id=mission_id,
                org_id=org_id,
                type="image",
                minio_key=f"test/mission/{mission_id}/img_{i}.jpg",
                size_bytes=1024 * 1024,
            )
            session.add(ma)

        await session.commit()

    # Act: call import endpoint
    client = AsyncClient(app=app, base_url="http://test")
    # For test we just check that it accepts the request and returns 200 with scene id
    response = await client.post(
        "/api/v1/scenes-import/from-mission",
        json={
            "mission_id": str(mission_id),
            "scene_kind": "3dgs",
        },
    )

    # Assert
    assert response.status_code == 200, f"expected 200 got {response.status_code}: {response.text}"
    data = response.json()
    assert "scene_id" in data
    assert data["n_imported"] == 2
    assert data["status"] == "ingested"

    # Cleanup is handled by transaction rollback in pytest-asyncio? we don't care for this test


async def test_import_non_completed_fails():
    """Cannot import a mission that's not yet completed."""
    async with AsyncSessionLocal() as session:
        org = Organization(name="Test Org", created_by="test")
        session.add(org)
        await session.flush()
        org_id = org.id

        user = User(email="test@example.com", org_id=org_id, role="system_officer")
        session.add(user)
        await session.flush()
        user_id = user.id

        mission = Mission(
            id=None,
            org_id=org_id,
            name="In Progress Mission",
            status="in_progress",
            created_by=user_id,
        )
        session.add(mission)
        await session.commit()
        mission_id = mission.id

    client = AsyncClient(app=app, base_url="http://test")
    response = await client.post(
        "/api/v1/scenes-import/from-mission",
        json={
            "mission_id": str(mission_id),
            "scene_kind": "3dgs",
        },
    )

    assert response.status_code == 409
    assert "only completed missions" in response.text.lower()


async def test_import_no_assets_fails():
    """Import fails when mission has zero importable assets."""
    async with AsyncSessionLocal() as session:
        org = Organization(name="Test Org", created_by="test")
        session.add(org)
        await session.flush()
        org_id = org.id

        user = User(email="test@example.com", org_id=org_id, role="system_officer")
        session.add(user)
        await session.flush()
        user_id = user.id

        mission = Mission(
            id=None,
            org_id=org_id,
            name="No Assets",
            status="completed",
            created_by=user_id,
        )
        session.add(mission)
        await session.commit()
        mission_id = mission.id

    client = AsyncClient(app=app, base_url="http://test")
    response = await client.post(
        "/api/v1/scenes-import/from-mission",
        json={
            "mission_id": str(mission_id),
            "scene_kind": "3dgs",
        },
    )

    assert response.status_code == 400
    assert "no importable" in response.text.lower()
