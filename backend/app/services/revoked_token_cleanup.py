"""Purge expired rows from ``revoked_tokens``.

Run via cron (e.g. every 6h) or invoke from a management command.

Rationale:
    A token whose ``exp`` has already passed cannot be replayed (signature
    verify rejects expired tokens), so keeping the row is wasteful.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete

from app.db import AsyncSessionLocal
from app.models.revoked_token import RevokedToken

logger = logging.getLogger(__name__)


async def cleanup_expired_revocations() -> int:
    """Delete rows with ``exp < now``. Returns the count of deleted rows."""
    now = datetime.now(tz=timezone.utc)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(RevokedToken).where(RevokedToken.exp < now)
        )
        await session.commit()
        deleted = result.rowcount or 0
        logger.info("Revoked-token cleanup: deleted %s expired rows", deleted)
        return deleted


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = await cleanup_expired_revocations()
    print(f"deleted={n}")


if __name__ == "__main__":
    asyncio.run(main())
