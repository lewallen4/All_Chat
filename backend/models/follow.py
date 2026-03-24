"""
All_Chat — Follow System
Users can follow each other. Followed users' posts appear first in a personalised feed.
"""

# ── Model ─────────────────────────────────────────────────────────────────────

from datetime import datetime, timezone
from sqlalchemy import Integer, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class Follow(Base):
    __tablename__ = "follows"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True)
    follower_id: Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                  nullable=False)
    following_id: Mapped[int]     = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                   nullable=False)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="uq_follow_pair"),
        Index("ix_follow_follower", "follower_id"),
        Index("ix_follow_following", "following_id"),
    )
