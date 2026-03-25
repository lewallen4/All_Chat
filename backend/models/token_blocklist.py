"""
All_Chat — Token Blocklist
Stores revoked refresh token JTIs in Redis (fast) with DB fallback.
Also used to invalidate all tokens for a user on logout/ban.
"""
from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class RevokedToken(Base):
    """Persistent fallback store for revoked JTIs."""
    __tablename__ = "revoked_tokens"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True)
    jti:        Mapped[str]      = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id:    Mapped[int]      = mapped_column(Integer, nullable=False, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_revoked_jti", "jti"),
        Index("ix_revoked_user", "user_id"),
    )
