"""RevokedToken model — JWT jti revocation list for /auth/logout & compromise response.

Any (jti, exp) row in this table causes decode_token()'s upstream
validation to reject that token even if the signature is valid.

Rows are pruned automatically once ``exp < now`` since the token would
have expired anyway — no need to keep an infinite blacklist.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # The token's original exp claim (unix seconds → we store as naive UTC dt).
    exp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
