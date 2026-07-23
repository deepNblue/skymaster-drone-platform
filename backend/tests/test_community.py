"""Test Community module endpoints (v2.2 E4)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_create_public_post_approved(auth_client: AsyncClient) -> None:
    """Happy path: create a clean public post gets approved immediately."""
    response = await auth_client.post(
        "/api/v1/community/posts",
        json={
            "title": "Hello SkyMaster Community",
            "body": "This is my first post about drone mapping experiences.",
            "tags": ["mapping", "beginner"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["moderation_status"] == "approved"
    assert "id" in data


async def test_create_post_blocked_keyword(auth_client: AsyncClient) -> None:
    """Post containing blocked keyword is auto-rejected."""
    response = await auth_client.post(
        "/api/v1/community/posts",
        json={
            "title": "Free crack for software",
            "body": "I have a crack for this tool, contact me...",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["moderation_status"] == "rejected"
    assert "crack" in data["moderation_reason"]


async def test_list_public_posts(auth_client: AsyncClient) -> None:
    """List public posts returns at least the one we just created."""
    # First create
    await auth_client.post(
        "/api/v1/community/posts",
        json={
            "title": "Test List Post",
            "body": "Testing the public listing endpoint",
        },
    )
    # Then list
    response = await auth_client.get("/api/v1/community/posts?page=1&size=10")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


async def test_add_comment_to_approved_post(auth_client: AsyncClient) -> None:
    """Can add comment to an approved post."""
    # Create post first
    create_resp = await auth_client.post(
        "/api/v1/community/posts",
        json={
            "title": "Post with comments",
            "body": "Feel free to comment here.",
        },
    )
    post_id = create_resp.json()["id"]

    comment_resp = await auth_client.post(
        f"/api/v1/community/posts/{post_id}/comments",
        json={"body": "Great post, thanks for sharing!"},
    )
    assert comment_resp.status_code == 200
    comment_data = comment_resp.json()
    assert comment_data["post_id"] == post_id
    assert "id" in comment_data

    # List comments
    list_resp = await auth_client.get(f"/api/v1/community/posts/{post_id}/comments")
    assert list_resp.status_code == 200
    comments = list_resp.json()
    assert len(comments) >= 1


async def test_like_unlike_post(auth_client: AsyncClient) -> None:
    """Like and unlike increments/decrements like_count correctly."""
    # Create post
    create_resp = await auth_client.post(
        "/api/v1/community/posts",
        json={
            "title": "Like this post",
            "body": "Testing the like functionality",
        },
    )
    post_id = create_resp.json()["id"]
    initial_likes = create_resp.json()["like_count"]

    # Like once
    like_resp = await auth_client.post(f"/api/v1/community/posts/{post_id}/like")
    assert like_resp.status_code == 200
    after_like = like_resp.json()["like_count"]
    assert after_like == initial_likes + 1

    # Like again is idempotent
    like_again_resp = await auth_client.post(f"/api/v1/community/posts/{post_id}/like")
    assert like_again_resp.json()["like_count"] == after_like

    # Unlike
    unlike_resp = await auth_client.delete(f"/api/v1/community/posts/{post_id}/like")
    assert unlike_resp.status_code == 200
    after_unlike = unlike_resp.json()["like_count"]
    assert after_unlike == initial_likes


async def test_cannot_comment_unapproved_post(auth_client: AsyncClient) -> None:
    """Cannot comment on a rejected post."""
    create_resp = await auth_client.post(
        "/api/v1/community/posts",
        json={
            "title": "Blocked post",
            "body": "This contains crack keyword",
        },
    )
    post_id = create_resp.json()["id"]
    assert create_resp.json()["moderation_status"] == "rejected"

    comment_resp = await auth_client.post(
        f"/api/v1/community/posts/{post_id}/comments",
        json={"body": "comment"},
    )
    assert comment_resp.status_code == 409
    assert "non-approved" in comment_resp.json()["detail"].lower()
