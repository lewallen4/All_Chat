"""
All_Chat — CommentVote Model
Per-user votes on comments (mirrors Vote model but for comments).
"""

from datetime import datetime, timezone
from sqlalchemy import Integer, ForeignKey, DateTime, SmallInteger, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class CommentVote(Base):
    __tablename__ = "comment_votes"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True)
    user_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                  nullable=False)
    comment_id: Mapped[int]      = mapped_column(Integer, ForeignKey("comments.id", ondelete="CASCADE"),
                                                  nullable=False)
    value:      Mapped[int]      = mapped_column(SmallInteger, nullable=False)  # +1 or -1
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "comment_id", name="uq_comment_vote"),
        Index("ix_comment_votes_comment", "comment_id"),
    )
