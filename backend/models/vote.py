"""
All_Chat - Vote Model
"""

from datetime import datetime, timezone
from sqlalchemy import Integer, ForeignKey, DateTime, SmallInteger, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class Vote(Base):
    __tablename__ = "votes"

    id:        Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    user_id:   Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                nullable=False)
    post_id:   Mapped[int]      = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"),
                                                nullable=False)
    value:     Mapped[int]      = mapped_column(SmallInteger, nullable=False)  # +1 or -1
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=lambda: datetime.now(timezone.utc))

    user: Mapped["User"] = relationship("User", back_populates="votes")
    post: Mapped["Post"] = relationship("Post", back_populates="votes")

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_vote_user_post"),
        Index("ix_votes_post_id", "post_id"),
    )
