"""
All_Chat - Post Model
Supports text, image, and link post types with Wilson score ranking.
Optional channel association, pinning support.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    String, Text, Integer, DateTime, ForeignKey, Float,
    Index, Boolean
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class Post(Base):
    __tablename__ = "posts"

    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    author_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    # Optional channel — NULL means general/uncategorised feed
    channel_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("channels.id", ondelete="SET NULL"),
                                                      nullable=True, index=True)
    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                   default=lambda: datetime.now(timezone.utc), index=True)
    updated_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                   default=lambda: datetime.now(timezone.utc),
                                                   onupdate=lambda: datetime.now(timezone.utc))
    is_deleted:   Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    is_pinned:    Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    removed_by_lead: Mapped[bool]  = mapped_column(Boolean, default=False, nullable=False)

    # Content (at least one must be set)
    title:        Mapped[str | None] = mapped_column(String(300), nullable=True)
    body:         Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path:   Mapped[str | None] = mapped_column(String(512), nullable=True)
    link_url:     Mapped[str | None] = mapped_column(String(2048), nullable=True)
    link_title:   Mapped[str | None] = mapped_column(String(300), nullable=True)
    link_preview: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Vote counts (denormalized for fast feed queries)
    upvotes:      Mapped[int]   = mapped_column(Integer, default=0, nullable=False)
    downvotes:    Mapped[int]   = mapped_column(Integer, default=0, nullable=False)
    wilson_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)

    # Full-text search vector — TSVECTOR on PostgreSQL, Text elsewhere
    search_vector: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    author:  Mapped["User"]          = relationship("User", back_populates="posts")
    votes:   Mapped[list["Vote"]]    = relationship("Vote", back_populates="post",
                                                     cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_posts_created_wilson",  "created_at", "wilson_score"),
        Index("ix_posts_author_created",  "author_id",  "created_at"),
        Index("ix_posts_channel_created", "channel_id", "created_at"),
    )

    def __repr__(self):
        return f"<Post id={self.id} author_id={self.author_id} channel_id={self.channel_id}>"
