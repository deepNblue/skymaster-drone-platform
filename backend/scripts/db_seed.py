"""Idempotent DB seed for e2e / SITL smoke testing.

Creates:
  * 1 Organization named "TestOrg"
  * 1 admin User (email=admin@test.local, password=admin123, role=admin)

Both are upserted — running the script twice is safe.

Usage:
    DATABASE_URL=postgresql+asyncpg://sm:sm@localhost:5432/skymaster \\
        python -m scripts.db_seed
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from sqlalchemy import select

# Make sure `app` is importable when the script is run directly.
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import AsyncSessionLocal  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import hash_password  # noqa: E402


SEED_ORG_NAME = "TestOrg"
SEED_USER_EMAIL = "admin@test.local"
SEED_USER_PASSWORD = "admin123"
SEED_USER_ROLE = "admin"


async def seed() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        # --- Org (upsert-by-name) ---
        org = (
            await db.execute(
                select(Organization).where(Organization.name == SEED_ORG_NAME)
            )
        ).scalar_one_or_none()
        if org is None:
            org = Organization(name=SEED_ORG_NAME, tenant_type="standard")
            db.add(org)
            await db.commit()
            await db.refresh(org)
            org_created = True
        else:
            org_created = False

        # --- User (upsert-by-email) ---
        user = (
            await db.execute(select(User).where(User.email == SEED_USER_EMAIL))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                org_id=org.id,
                email=SEED_USER_EMAIL,
                hashed_pw=hash_password(SEED_USER_PASSWORD),
                role=SEED_USER_ROLE,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            user_created = True
        else:
            user_created = False

        return {
            "org_id": str(org.id),
            "org_created": org_created,
            "user_id": str(user.id),
            "user_email": user.email,
            "user_created": user_created,
        }


def main() -> None:
    result = asyncio.run(seed())
    print("[db_seed] result:", result)
    print(
        f"[db_seed] login with: email={SEED_USER_EMAIL} password={SEED_USER_PASSWORD}"
    )


if __name__ == "__main__":
    main()
