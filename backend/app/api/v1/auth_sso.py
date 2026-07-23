"""OAuth2 / OIDC SSO — Google & GitHub.

Delegates to Authlib to avoid re-implementing the OAuth dance. Providers
are pluggable via env; missing client_id/secret means the provider is
simply not registered (and its endpoints return 404).

Env:
    OAUTH_GOOGLE_CLIENT_ID / OAUTH_GOOGLE_CLIENT_SECRET
    OAUTH_GITHUB_CLIENT_ID / OAUTH_GITHUB_CLIENT_SECRET
    OAUTH_REDIRECT_BASE (default: http://localhost:8000)

Flow:
    1. GET /auth/sso/{provider}/authorize  → 302 to provider auth URL
    2. Provider redirects back to /auth/sso/{provider}/callback?code=...
    3. Backend exchanges code, upserts User(email, sso_sub), issues JWT pair
    4. Response body includes access+refresh tokens (frontend picks up)

Design note:
    We keep this stateless — no session middleware needed. The `state`
    param is a signed JWT with a 5-minute TTL that carries the intent
    (next URL) and prevents CSRF at the redirect step.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

import httpx
from jose import jwt as _jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.services.auth import create_access_token, create_refresh_token, hash_password

router = APIRouter(prefix="/auth/sso", tags=["auth-sso"])


# ---------- Provider registry ----------------------------------------------

class _Provider:
    def __init__(
        self,
        name: str,
        client_id: str,
        client_secret: str,
        authorize_url: str,
        token_url: str,
        userinfo_url: str,
        scope: str,
    ):
        self.name = name
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorize_url = authorize_url
        self.token_url = token_url
        self.userinfo_url = userinfo_url
        self.scope = scope


def _providers() -> dict[str, _Provider]:
    out: dict[str, _Provider] = {}
    g_id = os.getenv("OAUTH_GOOGLE_CLIENT_ID")
    g_sec = os.getenv("OAUTH_GOOGLE_CLIENT_SECRET")
    if g_id and g_sec:
        out["google"] = _Provider(
            name="google",
            client_id=g_id,
            client_secret=g_sec,
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
            scope="openid email profile",
        )
    gh_id = os.getenv("OAUTH_GITHUB_CLIENT_ID")
    gh_sec = os.getenv("OAUTH_GITHUB_CLIENT_SECRET")
    if gh_id and gh_sec:
        out["github"] = _Provider(
            name="github",
            client_id=gh_id,
            client_secret=gh_sec,
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            scope="read:user user:email",
        )
    return out


def _redirect_uri(provider: str) -> str:
    base = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000")
    return f"{base}/api/v1/auth/sso/{provider}/callback"


# ---------- Signed-state helpers -------------------------------------------

_STATE_TTL_S = 300  # 5 min


def _sign_state(provider: str, next_url: str) -> str:
    return _jwt.encode(
        {
            "provider": provider,
            "next": next_url,
            "nonce": uuid4().hex,
            "iat": int(time.time()),
            "exp": int(time.time()) + _STATE_TTL_S,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_alg,
    )


def _verify_state(state: str) -> dict:
    try:
        return _jwt.decode(state, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except Exception:
        raise HTTPException(400, "Invalid or expired state")


# ---------- Endpoints -------------------------------------------------------

@router.get("/providers")
async def list_providers() -> dict:
    """List provider names available in this deployment."""
    return {"providers": list(_providers().keys())}


@router.get("/{provider}/authorize")
async def authorize(
    provider: str, request: Request, next: str = "/dashboard"
) -> RedirectResponse:
    reg = _providers().get(provider)
    if reg is None:
        raise HTTPException(404, f"Provider '{provider}' not configured")
    state = _sign_state(provider, next)
    from urllib.parse import urlencode
    params = {
        "client_id": reg.client_id,
        "redirect_uri": _redirect_uri(provider),
        "response_type": "code",
        "scope": reg.scope,
        "state": state,
    }
    return RedirectResponse(f"{reg.authorize_url}?{urlencode(params)}")


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    reg = _providers().get(provider)
    if reg is None:
        raise HTTPException(404, f"Provider '{provider}' not configured")
    claims = _verify_state(state)
    if claims.get("provider") != provider:
        raise HTTPException(400, "State provider mismatch")

    # Exchange code for access token.
    async with httpx.AsyncClient(timeout=8.0) as client:
        token_resp = await client.post(
            reg.token_url,
            data={
                "code": code,
                "client_id": reg.client_id,
                "client_secret": reg.client_secret,
                "redirect_uri": _redirect_uri(provider),
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(400, f"Token exchange failed: {token_resp.text[:200]}")
        tok = token_resp.json()
        access_token = tok.get("access_token")
        if not access_token:
            raise HTTPException(400, "No access_token in provider response")

        # Fetch userinfo.
        ui_resp = await client.get(
            reg.userinfo_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if ui_resp.status_code != 200:
            raise HTTPException(400, "Userinfo fetch failed")
        info = ui_resp.json()

    email = info.get("email")
    sso_sub = str(info.get("sub") or info.get("id") or "")
    if provider == "github" and not email:
        # GitHub sometimes hides email — fetch /user/emails
        async with httpx.AsyncClient(timeout=6.0) as client:
            er = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if er.status_code == 200:
                for e in er.json():
                    if e.get("primary") and e.get("verified"):
                        email = e["email"]
                        break
    if not email:
        raise HTTPException(400, "Provider did not return an email address")

    # Upsert user.
    row = await db.execute(select(User).where(User.email == email))
    user = row.scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            hashed_pw=hash_password(uuid4().hex),  # random-unusable password
            role="operator",
            sso_sub=sso_sub or None,
        )
        db.add(user)
    else:
        # Backfill sso_sub on first SSO login.
        if not user.sso_sub and sso_sub:
            user.sso_sub = sso_sub

    if getattr(user, "is_active", True) is False:
        raise HTTPException(403, "Account is deactivated")

    await db.commit()
    await db.refresh(user)

    access = create_access_token(user_id=user.id, org_id=user.org_id, role=user.role)
    refresh = create_refresh_token(user_id=user.id, org_id=user.org_id, role=user.role)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_min * 60,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
            "org_id": str(user.org_id) if user.org_id else None,
        },
        "next": claims.get("next", "/dashboard"),
    }
