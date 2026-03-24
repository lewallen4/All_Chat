"""
All_Chat — Channel & ChannelMembership Models

Permission hierarchy:
  ADMIN (global, stored on User.is_admin) — overrides everything
  CHIEF_LEAD  — full lead permissions in their channel, cannot be demoted by other leads
  LEAD        — subset of permissions granted by chief or admin
  MEMBER      — regular joined member
  BANNED      — channel-banned, read-only at most

Lead permissions are stored as an integer bitmask on ChannelMembership.permissions.
Each bit corresponds to a capability defined in LeadPermission below.
Chief Leads always have ALL bits set.
"""

from datetime import datetime, timezone
from enum import IntFlag

from sqlalchemy import (
    Integer, String, Text, Boolean, DateTime,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


# ── Permission bitmask ────────────────────────────────────────────────────────

class LeadPermission(IntFlag):
    """
    Bitflag enum for lead permissions.
    Store as integer column; test with: membership.permissions & LeadPermission.CAN_BAN
    """
    NONE               = 0
    CAN_BAN            = 1 << 0   # 1   — ban/unban channel members
    CAN_MANAGE_POSTS   = 1 << 1   # 2   — delete/restore posts, mark [removed]
    CAN_MANAGE_COMMENTS= 1 << 2   # 4   — delete/restore comments
    CAN_MANAGE_LEADS   = 1 << 3   # 8   — promote/demote leads (up to own rank)
    CAN_EDIT_CHANNEL   = 1 << 4   # 16  — edit name, description, avatar, rules
    CAN_PIN_POSTS      = 1 << 5   # 32  — pin/unpin posts in channel

    # Convenience combos
    ALL   = CAN_BAN | CAN_MANAGE_POSTS | CAN_MANAGE_COMMENTS | CAN_MANAGE_LEADS | CAN_EDIT_CHANNEL | CAN_PIN_POSTS
    BASIC = CAN_BAN | CAN_MANAGE_POSTS | CAN_MANAGE_COMMENTS


# ── Role constants ────────────────────────────────────────────────────────────

class MemberRole:
    CHIEF_LEAD = "chief_lead"
    LEAD       = "lead"
    MEMBER     = "member"
    BANNED     = "banned"

    @staticmethod
    def rank(role: str) -> int:
        return {"chief_lead": 3, "lead": 2, "member": 1, "banned": 0}.get(role, 0)


# ── Channel model ─────────────────────────────────────────────────────────────

class Channel(Base):
    __tablename__ = "channels"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    slug:        Mapped[str]      = mapped_column(String(64),  unique=True, nullable=False, index=True)
    name:        Mapped[str]      = mapped_column(String(80),  nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules:       Mapped[str | None] = mapped_column(Text, nullable=True)     # markdown
    avatar_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    banner_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_private:  Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    is_locked:   Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)  # no new posts
    is_archived: Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)  # admin-dissolved
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=lambda: datetime.now(timezone.utc))
    creator_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                                                  nullable=True)

    # Denormalized counts for fast display
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    post_count:   Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    memberships: Mapped[list["ChannelMembership"]] = relationship(
        "ChannelMembership", back_populates="channel", cascade="all, delete-orphan"
    )
    creator: Mapped["User"] = relationship("User", foreign_keys=[creator_id])

    def __repr__(self):
        return f"<Channel slug={self.slug}>"


# ── ChannelMembership model ───────────────────────────────────────────────────

class ChannelMembership(Base):
    __tablename__ = "channel_memberships"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    channel_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("channels.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    user_id:     Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                  nullable=False, index=True)
    role:        Mapped[str]      = mapped_column(String(16), nullable=False, default=MemberRole.MEMBER)
    # Bitmask of LeadPermission flags (0 for regular members and banned users)
    permissions: Mapped[int]      = mapped_column(Integer, default=0, nullable=False)
    joined_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  default=lambda: datetime.now(timezone.utc))
    # Display title shown on profile and posts (e.g. "Moderator", "News Bot")
    title:       Mapped[str | None] = mapped_column(String(64), nullable=True)

    channel: Mapped["Channel"] = relationship("Channel", back_populates="memberships")
    user:    Mapped["User"]    = relationship("User")

    # ── Permission helpers ────────────────────────────────────────────────────

    def has_perm(self, perm: LeadPermission) -> bool:
        if self.role == MemberRole.CHIEF_LEAD:
            return True
        return bool(self.permissions & perm)

    def is_lead_or_above(self) -> bool:
        return self.role in (MemberRole.CHIEF_LEAD, MemberRole.LEAD)

    def outranks(self, other: "ChannelMembership") -> bool:
        return MemberRole.rank(self.role) > MemberRole.rank(other.role)

    __table_args__ = (
        UniqueConstraint("channel_id", "user_id", name="uq_channel_member"),
        Index("ix_cm_channel_role", "channel_id", "role"),
    )

    def __repr__(self):
        return f"<ChannelMembership channel={self.channel_id} user={self.user_id} role={self.role}>"
