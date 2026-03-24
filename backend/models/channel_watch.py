"""
All_Chat — ChannelWatch Model
Users can "watch" channels to see their posts in the curated feed.
Watching is distinct from membership — you can watch without being a member
of a public channel (viewing only), and members aren't auto-watching.
"""

from datetime import datetime, timezone
from sqlalchemy import Integer, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class ChannelWatch(Base):
    __tablename__ = "channel_watches"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    channel_id: Mapped[int]      = mapped_column(Integer, ForeignKey("channels.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", name="uq_channel_watch"),
        Index("ix_watch_user",    "user_id"),
        Index("ix_watch_channel", "channel_id"),
    )
