"""
All_Chat — Bookmarks
Users can save posts to their personal bookmark list.
"""

from datetime import datetime, timezone
from sqlalchemy import Integer, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)
    post_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"),
                                                 nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_bookmark_user_post"),
        Index("ix_bookmark_user_created", "user_id", "created_at"),
    )
