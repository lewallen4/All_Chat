"""
All_Chat - User Model
"""

from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Text, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class User(Base):
    __tablename__ = "users"

    id:             Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    username:       Mapped[str]      = mapped_column(String(32), unique=True, nullable=False, index=True)
    email:          Mapped[str]      = mapped_column(String(254), unique=True, nullable=False, index=True)
    password_hash:  Mapped[str]      = mapped_column(String(256), nullable=False)
    email_verified: Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    is_active:      Mapped[bool]     = mapped_column(Boolean, default=True, nullable=False)
    is_admin:       Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    created_at:     Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                      default=lambda: datetime.now(timezone.utc))

    # Profile
    bio_markdown:   Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_path:    Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_name:   Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Post-Quantum DM keys (public stored server-side, private stored client-side ONLY)
    pq_public_key:  Mapped[str | None] = mapped_column(Text, nullable=True)  # base64

    # Relationships
    posts:          Mapped[list["Post"]]    = relationship("Post", back_populates="author", lazy="select")
    votes:          Mapped[list["Vote"]]    = relationship("Vote", back_populates="user",   lazy="select")
    sent_messages:  Mapped[list["Message"]] = relationship("Message", foreign_keys="Message.sender_id",
                                                            back_populates="sender", lazy="select")
    recv_messages:  Mapped[list["Message"]] = relationship("Message", foreign_keys="Message.recipient_id",
                                                            back_populates="recipient", lazy="select")

    __table_args__ = (
        Index("ix_users_username_lower", "username"),
    )

    def __repr__(self):
        return f"<User id={self.id} username={self.username}>"
