"""
All_Chat — Notifications
In-app notification system for votes, mentions, new followers, new messages.
"""

# ── Model ─────────────────────────────────────────────────────────────────────

from datetime import datetime, timezone
from sqlalchemy import Integer, ForeignKey, DateTime, Boolean, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    user_id:     Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    actor_id:    Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                                                    nullable=True)
    kind:        Mapped[str]      = mapped_column(String(32), nullable=False)
    # kind: "upvote" | "downvote" | "follow" | "message" | "mention"
    post_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"),
                                                    nullable=True)
    body:        Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read:     Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=lambda: datetime.now(timezone.utc), index=True)

    user:  Mapped["User"] = relationship("User", foreign_keys=[user_id])
    actor: Mapped["User"] = relationship("User", foreign_keys=[actor_id])

    __table_args__ = (
        Index("ix_notif_user_unread", "user_id", "is_read", "created_at"),
    )
