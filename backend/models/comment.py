"""
All_Chat — Comments
Threaded comments on posts. One level of nesting (top-level + replies).
Full-text indexed, soft-deletable, Wilson-scored.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Integer, ForeignKey, DateTime, Text, Boolean, Float, Index
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id:           Mapped[int]       = mapped_column(Integer, primary_key=True, index=True)
    post_id:      Mapped[int]       = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"),
                                                    nullable=False, index=True)
    author_id:    Mapped[int]       = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                    nullable=False)
    parent_id:    Mapped[int | None] = mapped_column(Integer, ForeignKey("comments.id", ondelete="CASCADE"),
                                                     nullable=True, index=True)
    body:         Mapped[str]       = mapped_column(Text, nullable=False)
    is_deleted:   Mapped[bool]      = mapped_column(Boolean, default=False, nullable=False)
    upvotes:      Mapped[int]       = mapped_column(Integer, default=0, nullable=False)
    downvotes:    Mapped[int]       = mapped_column(Integer, default=0, nullable=False)
    wilson_score: Mapped[float]     = mapped_column(Float, default=0.0, nullable=False)
    created_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True),
                                                    default=lambda: datetime.now(timezone.utc), index=True)
    updated_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True),
                                                    default=lambda: datetime.now(timezone.utc),
                                                    onupdate=lambda: datetime.now(timezone.utc))

    author:   Mapped["User"]          = relationship("User")
    post:     Mapped["Post"]          = relationship("Post")
    replies:  Mapped[list["Comment"]] = relationship("Comment", back_populates="parent")
    parent:   Mapped["Comment | None"] = relationship("Comment", back_populates="replies",
                                                       remote_side=[id])

    __table_args__ = (
        Index("ix_comments_post_created", "post_id", "created_at"),
    )
