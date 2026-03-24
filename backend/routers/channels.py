"""
All_Chat — Channels Router

Permission enforcement:
  Admin           → can do anything to any channel (bypass all checks)
  Chief Lead      → all permissions in their channel
  Lead w/ perm    → specific granted permissions only
  Member          → read + post (if channel not locked)
  Banned          → read-only, cannot post/comment/vote
  Non-member      → public channels: read-only. Private: no access.

Slug rules: lowercase, letters/numbers/hyphens, 3-64 chars.
"""

import re
import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, Depends, HTTPException, status,
    Query, UploadFile, File, Form
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, update, and_
from pydantic import BaseModel, field_validator
from PIL import Image

from core.database import get_db
from core.deps import get_current_user, get_current_user_optional
from core.config import settings
from core.security import sanitize_text, sanitize_html
from models.user import User
from models.post import Post
from models.vote import Vote
from models.channel import Channel, ChannelMembership, LeadPermission, MemberRole
from models.notification import Notification
from schemas.schemas import PostResponse, UserPublic, MessageOut

router = APIRouter()

SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$')


# ══ Schemas ════════════════════════════════════════════════════════════════════

class ChannelCreate(BaseModel):
    slug:        str
    name:        str
    description: Optional[str] = None
    rules:       Optional[str] = None
    is_private:  bool = False

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v):
        v = v.lower().strip()
        if not SLUG_RE.match(v):
            raise ValueError("Slug must be 3–64 chars, lowercase letters, numbers, hyphens only, "
                             "and cannot start or end with a hyphen.")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        v = sanitize_text(v).strip()
        if len(v) < 2:   raise ValueError("Name must be at least 2 characters.")
        if len(v) > 80:  raise ValueError("Name too long (max 80 chars).")
        return v

    @field_validator("description")
    @classmethod
    def validate_desc(cls, v):
        if v:
            v = sanitize_html(v)
            if len(v) > 2000: raise ValueError("Description too long (max 2000 chars).")
        return v


class ChannelUpdate(BaseModel):
    name:        Optional[str] = None
    description: Optional[str] = None
    rules:       Optional[str] = None
    is_private:  Optional[bool] = None
    is_locked:   Optional[bool] = None


class ChannelOut(BaseModel):
    id:           int
    slug:         str
    name:         str
    description:  Optional[str]
    rules:        Optional[str]
    avatar_path:  Optional[str]
    banner_path:  Optional[str]
    is_private:   bool
    is_locked:    bool
    is_archived:  bool
    member_count: int
    post_count:   int
    created_at:   datetime
    # Viewer's membership (injected per-request)
    viewer_role:       Optional[str]  = None
    viewer_permissions: Optional[int] = None
    viewer_title:      Optional[str]  = None

    model_config = {"from_attributes": True}


class MemberOut(BaseModel):
    user:        UserPublic
    role:        str
    permissions: int
    title:       Optional[str]
    joined_at:   datetime

    model_config = {"from_attributes": True}


class SetLeadRequest(BaseModel):
    username:    str
    role:        str   # "lead" or "member" (to demote)
    permissions: int = int(LeadPermission.BASIC)
    title:       Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in (MemberRole.LEAD, MemberRole.MEMBER):
            raise ValueError("Role must be 'lead' or 'member'.")
        return v

    @field_validator("permissions")
    @classmethod
    def validate_perms(cls, v):
        if v < 0 or v > int(LeadPermission.ALL):
            raise ValueError("Invalid permissions bitmask.")
        return v


class BanRequest(BaseModel):
    username: str
    reason:   Optional[str] = None


# ══ Helpers ════════════════════════════════════════════════════════════════════

async def _get_channel(db: AsyncSession, slug: str) -> Channel:
    r = await db.execute(select(Channel).where(Channel.slug == slug, Channel.is_archived == False))
    ch = r.scalar_one_or_none()
    if not ch:
        raise HTTPException(404, f"Channel '{slug}' not found.")
    return ch


async def _get_membership(db: AsyncSession, channel_id: int, user_id: int) -> Optional[ChannelMembership]:
    r = await db.execute(
        select(ChannelMembership).where(
            ChannelMembership.channel_id == channel_id,
            ChannelMembership.user_id    == user_id,
        )
    )
    return r.scalar_one_or_none()


def _require_perm(membership: Optional[ChannelMembership], perm: LeadPermission,
                  current_user: User, label: str = "perform this action"):
    """Raise 403 unless user is admin or has the required permission."""
    if current_user.is_admin:
        return
    if not membership or not membership.has_perm(perm):
        raise HTTPException(403, f"You do not have permission to {label}.")


def _require_lead(membership: Optional[ChannelMembership], current_user: User):
    if current_user.is_admin:
        return
    if not membership or not membership.is_lead_or_above():
        raise HTTPException(403, "Lead or admin access required.")


def _check_not_banned(membership: Optional[ChannelMembership]):
    if membership and membership.role == MemberRole.BANNED:
        raise HTTPException(403, "You are banned from this channel.")


def _build_channel_out(ch: Channel, membership: Optional[ChannelMembership]) -> ChannelOut:
    return ChannelOut(
        id=ch.id, slug=ch.slug, name=ch.name,
        description=ch.description, rules=ch.rules,
        avatar_path=ch.avatar_path, banner_path=ch.banner_path,
        is_private=ch.is_private, is_locked=ch.is_locked, is_archived=ch.is_archived,
        member_count=ch.member_count, post_count=ch.post_count,
        created_at=ch.created_at,
        viewer_role        = membership.role        if membership else None,
        viewer_permissions = membership.permissions if membership else None,
        viewer_title       = membership.title       if membership else None,
    )


# ══ Channel CRUD ═══════════════════════════════════════════════════════════════

@router.get("", response_model=dict)
async def list_channels(
    page: int = Query(1, ge=1),
    q:    str = Query("", max_length=100),
    db:   AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Public channel directory. Private channels shown only to members/admins."""
    page_size = 24
    offset    = (page - 1) * page_size

    query = select(Channel).where(Channel.is_archived == False)

    # Hide private channels from non-members (unless admin)
    if not (current_user and current_user.is_admin):
        if current_user:
            # Show public + private channels where user is a member
            member_ids = select(ChannelMembership.channel_id).where(
                ChannelMembership.user_id == current_user.id,
                ChannelMembership.role    != MemberRole.BANNED,
            )
            query = query.where(
                (Channel.is_private == False) | (Channel.id.in_(member_ids))
            )
        else:
            query = query.where(Channel.is_private == False)

    if q:
        query = query.where(
            Channel.name.ilike(f"%{q}%") | Channel.slug.ilike(f"%{q}%")
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(desc(Channel.member_count), desc(Channel.created_at))
             .offset(offset).limit(page_size)
    )
    channels = result.scalars().all()

    # Attach viewer membership
    out = []
    for ch in channels:
        ms = await _get_membership(db, ch.id, current_user.id) if current_user else None
        out.append(_build_channel_out(ch, ms))

    return {"channels": out, "total": total, "page": page,
            "has_more": (offset + len(channels)) < total}


@router.post("", response_model=ChannelOut, status_code=201)
async def create_channel(
    req:          ChannelCreate,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """Any verified user can create a channel and becomes its Chief Lead."""
    existing = await db.execute(select(Channel).where(Channel.slug == req.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Channel '{req.slug}' already exists.")

    ch = Channel(
        slug=req.slug, name=req.name, description=req.description,
        rules=req.rules, is_private=req.is_private,
        creator_id=current_user.id, member_count=1, post_count=0,
    )
    db.add(ch)
    await db.flush()  # get ch.id

    # Creator becomes Chief Lead with all permissions
    ms = ChannelMembership(
        channel_id=ch.id, user_id=current_user.id,
        role=MemberRole.CHIEF_LEAD, permissions=int(LeadPermission.ALL),
    )
    db.add(ms)
    await db.flush()
    return _build_channel_out(ch, ms)


@router.get("/{slug}", response_model=ChannelOut)
async def get_channel(
    slug:         str,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id) if current_user else None

    # Private channel — only members + admins
    if ch.is_private:
        if not current_user or (not current_user.is_admin and
                                (not ms or ms.role == MemberRole.BANNED)):
            raise HTTPException(404, f"Channel '{slug}' not found.")

    return _build_channel_out(ch, ms)


@router.patch("/{slug}", response_model=ChannelOut)
async def update_channel(
    slug:         str,
    req:          ChannelUpdate,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    _require_perm(ms, LeadPermission.CAN_EDIT_CHANNEL, current_user, "edit this channel")

    if req.name        is not None: ch.name        = sanitize_text(req.name)
    if req.description is not None: ch.description = sanitize_html(req.description)
    if req.rules       is not None: ch.rules       = sanitize_html(req.rules)
    if req.is_private  is not None: ch.is_private  = req.is_private
    if req.is_locked   is not None:
        # Only chief lead or admin can lock/unlock
        if not current_user.is_admin and (not ms or ms.role != MemberRole.CHIEF_LEAD):
            raise HTTPException(403, "Only the Chief Lead or admin can lock/unlock a channel.")
        ch.is_locked = req.is_locked

    await db.flush()
    ms = await _get_membership(db, ch.id, current_user.id)
    return _build_channel_out(ch, ms)


# ══ Membership ═════════════════════════════════════════════════════════════════

@router.post("/{slug}/join", response_model=MessageOut)
async def join_channel(
    slug:         str,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    if ch.is_private:
        raise HTTPException(403, "This channel is private. Ask a Lead for an invite.")

    ms = await _get_membership(db, ch.id, current_user.id)
    if ms:
        if ms.role == MemberRole.BANNED:
            raise HTTPException(403, "You are banned from this channel.")
        return {"message": "Already a member."}

    db.add(ChannelMembership(channel_id=ch.id, user_id=current_user.id,
                              role=MemberRole.MEMBER, permissions=0))
    ch.member_count += 1
    await db.flush()
    return {"message": f"Joined #{ch.slug}!"}


@router.post("/{slug}/leave", response_model=MessageOut)
async def leave_channel(
    slug:         str,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    if not ms:
        return {"message": "Not a member."}

    if ms.role == MemberRole.CHIEF_LEAD:
        # Count other leads to prevent orphaned channel
        other_leads = await db.execute(
            select(func.count()).select_from(ChannelMembership).where(
                ChannelMembership.channel_id == ch.id,
                ChannelMembership.user_id    != current_user.id,
                ChannelMembership.role.in_([MemberRole.CHIEF_LEAD, MemberRole.LEAD]),
            )
        )
        if (other_leads.scalar() or 0) == 0:
            raise HTTPException(400,
                "You are the only lead. Promote another member to Lead before leaving, "
                "or delete the channel.")

    await db.delete(ms)
    ch.member_count = max(0, ch.member_count - 1)
    await db.flush()
    return {"message": f"Left #{ch.slug}."}


@router.get("/{slug}/members", response_model=dict)
async def list_members(
    slug:   str,
    page:   int = Query(1, ge=1),
    role:   str = Query("", max_length=20),
    db:     AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id) if current_user else None

    if ch.is_private and not (current_user and current_user.is_admin) and \
       (not ms or ms.role == MemberRole.BANNED):
        raise HTTPException(404, "Channel not found.")

    page_size = 30
    offset    = (page - 1) * page_size

    query = select(ChannelMembership).where(
        ChannelMembership.channel_id == ch.id,
        ChannelMembership.role != MemberRole.BANNED,
    )
    if role:
        query = query.where(ChannelMembership.role == role)

    total  = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(query.offset(offset).limit(page_size))
    memberships = result.scalars().all()

    out = []
    for m in memberships:
        await db.refresh(m, ["user"])
        u = m.user
        out.append({
            "user": {
                "id": u.id, "username": u.username,
                "display_name": u.display_name,
                "avatar_path": u.avatar_path,
                "bio_markdown": u.bio_markdown,
                "created_at": u.created_at.isoformat(),
                "pq_public_key": u.pq_public_key,
            },
            "role":        m.role,
            "permissions": m.permissions,
            "title":       m.title,
            "joined_at":   m.joined_at.isoformat(),
        })

    return {"members": out, "total": total, "page": page,
            "has_more": (offset + len(out)) < total}


# ══ Lead management ═════════════════════════════════════════════════════════════

@router.post("/{slug}/leads/set", response_model=MessageOut)
async def set_lead(
    slug:         str,
    req:          SetLeadRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """
    Promote a member to Lead, update an existing Lead's permissions,
    or demote a Lead back to Member.
    - Leads can promote up to Lead but cannot set permissions they don't have themselves.
    - Only Chief Lead or Admin can grant CAN_MANAGE_LEADS or full permission sets.
    - Cannot target Chief Lead (protected).
    """
    ch  = await _get_channel(db, slug)
    ms  = await _get_membership(db, ch.id, current_user.id)
    _require_lead(ms, current_user)

    # Resolve target
    target_r = await db.execute(select(User).where(User.username == req.username.lower()))
    target   = target_r.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found.")

    target_ms = await _get_membership(db, ch.id, target.id)
    if not target_ms or target_ms.role == MemberRole.BANNED:
        raise HTTPException(400, "Target is not an active member of this channel.")

    # Protect Chief Lead from being demoted by other leads
    if target_ms.role == MemberRole.CHIEF_LEAD and not current_user.is_admin:
        raise HTTPException(403, "The Chief Lead cannot be demoted by another Lead.")

    # Leads cannot promote to Chief Lead
    if req.role == MemberRole.CHIEF_LEAD:
        raise HTTPException(400, "Use /transfer-chief to transfer Chief Lead status.")

    # Leads can only grant permissions they themselves hold
    if not current_user.is_admin and ms and ms.role != MemberRole.CHIEF_LEAD:
        requested = LeadPermission(req.permissions)
        my_perms  = LeadPermission(ms.permissions)
        if (requested & ~my_perms) != LeadPermission.NONE:
            raise HTTPException(403, "You cannot grant permissions you don't have yourself.")

    target_ms.role        = req.role
    target_ms.permissions = req.permissions if req.role == MemberRole.LEAD else 0
    target_ms.title       = sanitize_text(req.title) if req.title else None
    await db.flush()

    # Notify target
    db.add(Notification(
        user_id=target.id, actor_id=current_user.id, kind="channel_role",
        body=f"Your role in #{ch.slug} has been updated to {req.role}."
    ))
    return {"message": f"@{target.username} is now {req.role} in #{ch.slug}."}


@router.post("/{slug}/leads/transfer-chief", response_model=MessageOut)
async def transfer_chief(
    slug:         str,
    username:     str,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """Transfer Chief Lead status to another member (current Chief Lead or Admin only)."""
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)

    if not current_user.is_admin and (not ms or ms.role != MemberRole.CHIEF_LEAD):
        raise HTTPException(403, "Only the current Chief Lead or an admin can transfer this role.")

    target_r  = await db.execute(select(User).where(User.username == username.lower()))
    target    = target_r.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found.")

    target_ms = await _get_membership(db, ch.id, target.id)
    if not target_ms or target_ms.role == MemberRole.BANNED:
        raise HTTPException(400, "Target must be an active member of this channel.")

    # Demote current chief to Lead (unless admin transferring on behalf)
    if ms and ms.role == MemberRole.CHIEF_LEAD:
        ms.role        = MemberRole.LEAD
        ms.permissions = int(LeadPermission.ALL)

    target_ms.role        = MemberRole.CHIEF_LEAD
    target_ms.permissions = int(LeadPermission.ALL)
    await db.flush()

    db.add(Notification(
        user_id=target.id, actor_id=current_user.id, kind="channel_role",
        body=f"You are now the Chief Lead of #{ch.slug}!"
    ))
    return {"message": f"@{target.username} is now the Chief Lead of #{ch.slug}."}


# ══ Banning ═════════════════════════════════════════════════════════════════════

@router.post("/{slug}/ban", response_model=MessageOut)
async def ban_member(
    slug:         str,
    req:          BanRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    _require_perm(ms, LeadPermission.CAN_BAN, current_user, "ban members")

    target_r  = await db.execute(select(User).where(User.username == req.username.lower()))
    target    = target_r.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found.")
    if target.id == current_user.id:
        raise HTTPException(400, "Cannot ban yourself.")

    target_ms = await _get_membership(db, ch.id, target.id)

    # Leads cannot ban equal/higher ranks
    if not current_user.is_admin and target_ms:
        if not (ms and ms.outranks(target_ms)):
            raise HTTPException(403, "Cannot ban someone with equal or higher rank.")

    if target_ms:
        target_ms.role        = MemberRole.BANNED
        target_ms.permissions = 0
    else:
        db.add(ChannelMembership(channel_id=ch.id, user_id=target.id,
                                  role=MemberRole.BANNED, permissions=0))
        ch.member_count = max(0, ch.member_count - 1)

    db.add(Notification(
        user_id=target.id, actor_id=current_user.id, kind="channel_ban",
        body=f"You have been banned from #{ch.slug}.{' Reason: ' + req.reason if req.reason else ''}"
    ))
    await db.flush()
    return {"message": f"@{target.username} has been banned from #{ch.slug}."}


@router.post("/{slug}/unban", response_model=MessageOut)
async def unban_member(
    slug:     str,
    username: str,
    current_user: User = Depends(get_current_user),
    db:       AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    _require_perm(ms, LeadPermission.CAN_BAN, current_user, "unban members")

    target_r  = await db.execute(select(User).where(User.username == username.lower()))
    target    = target_r.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found.")

    target_ms = await _get_membership(db, ch.id, target.id)
    if not target_ms or target_ms.role != MemberRole.BANNED:
        raise HTTPException(400, f"@{username} is not banned.")

    target_ms.role = MemberRole.MEMBER
    ch.member_count += 1
    await db.flush()
    return {"message": f"@{username} has been unbanned from #{ch.slug}."}


# ══ Post moderation ══════════════════════════════════════════════════════════════

@router.post("/{slug}/posts/{post_id}/remove", response_model=MessageOut)
async def lead_remove_post(
    slug:         str,
    post_id:      int,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """Remove a post from channel (marks as [post removed], keeps record)."""
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    _require_perm(ms, LeadPermission.CAN_MANAGE_POSTS, current_user, "remove posts")

    post_r = await db.execute(select(Post).where(Post.id == post_id, Post.channel_id == ch.id))
    post   = post_r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found in this channel.")

    post.removed_by_lead = True
    post.is_deleted      = True
    await db.flush()
    return {"message": "Post removed."}


@router.post("/{slug}/posts/{post_id}/restore", response_model=MessageOut)
async def lead_restore_post(
    slug:         str,
    post_id:      int,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    _require_perm(ms, LeadPermission.CAN_MANAGE_POSTS, current_user, "restore posts")

    post_r = await db.execute(select(Post).where(Post.id == post_id, Post.channel_id == ch.id))
    post   = post_r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found in this channel.")

    post.removed_by_lead = False
    post.is_deleted      = False
    await db.flush()
    return {"message": "Post restored."}


@router.post("/{slug}/posts/{post_id}/pin", response_model=MessageOut)
async def pin_post(
    slug:         str,
    post_id:      int,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    _require_perm(ms, LeadPermission.CAN_PIN_POSTS, current_user, "pin posts")

    post_r = await db.execute(select(Post).where(Post.id == post_id, Post.channel_id == ch.id))
    post   = post_r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found in this channel.")

    post.is_pinned = not post.is_pinned
    await db.flush()
    action = "pinned" if post.is_pinned else "unpinned"
    return {"message": f"Post {action}."}


# ══ Channel feed ════════════════════════════════════════════════════════════════

@router.get("/{slug}/posts", response_model=dict)
async def channel_feed(
    slug:   str,
    sort:   str = Query("new", pattern="^(new|top|hot)$"),
    period: str = Query("all", pattern="^(24h|week|month|year|all)$"),
    page:   int = Query(1, ge=1),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db:     AsyncSession = Depends(get_db),
):
    from datetime import timedelta
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id) if current_user else None

    if ch.is_private and not (current_user and current_user.is_admin) and \
       (not ms or ms.role == MemberRole.BANNED):
        raise HTTPException(404, "Channel not found.")

    page_size = 25
    offset    = (page - 1) * page_size

    # Time filter
    now = datetime.now(timezone.utc)
    time_filters = {"24h": timedelta(hours=24), "week": timedelta(weeks=1),
                    "month": timedelta(days=30), "year": timedelta(days=365)}
    q = select(Post).where(Post.channel_id == ch.id, Post.is_deleted == False)
    if period in time_filters:
        q = q.where(Post.created_at >= now - time_filters[period])

    if sort == "new":    q = q.order_by(Post.is_pinned.desc(), desc(Post.created_at))
    elif sort == "top":  q = q.order_by(Post.is_pinned.desc(), desc(Post.wilson_score), desc(Post.created_at))
    elif sort == "hot":  q = q.order_by(Post.is_pinned.desc(), desc(Post.wilson_score), desc(Post.upvotes), desc(Post.created_at))

    total  = (await db.execute(select(func.count()).select_from(
        select(Post).where(Post.channel_id == ch.id, Post.is_deleted == False).subquery()
    ))).scalar() or 0
    result = await db.execute(q.offset(offset).limit(page_size))
    posts  = result.scalars().all()

    out = []
    for p in posts:
        await db.refresh(p, ["author"])
        user_vote = None
        if current_user:
            vr = await db.execute(select(Vote.value).where(Vote.user_id == current_user.id, Vote.post_id == p.id))
            user_vote = vr.scalar_one_or_none()
        out.append(_build_post_response(p, user_vote))

    return {"posts": out, "total": total, "page": page,
            "has_more": (offset + len(posts)) < total,
            "channel": _build_channel_out(ch, ms)}


# ══ Image uploads ════════════════════════════════════════════════════════════════

@router.post("/{slug}/avatar", response_model=MessageOut)
async def upload_channel_avatar(
    slug:         str,
    file:         UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    _require_perm(ms, LeadPermission.CAN_EDIT_CHANNEL, current_user, "edit channel avatar")

    path = await _save_channel_image(file, "avatars", 200)
    if ch.avatar_path:
        _delete_media_file(ch.avatar_path)
    ch.avatar_path = path
    await db.flush()
    return {"message": "Channel avatar updated."}


@router.post("/{slug}/banner", response_model=MessageOut)
async def upload_channel_banner(
    slug:         str,
    file:         UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    ch = await _get_channel(db, slug)
    ms = await _get_membership(db, ch.id, current_user.id)
    _require_perm(ms, LeadPermission.CAN_EDIT_CHANNEL, current_user, "edit channel banner")

    path = await _save_channel_image(file, "banners", 1920)
    if ch.banner_path:
        _delete_media_file(ch.banner_path)
    ch.banner_path = path
    await db.flush()
    return {"message": "Channel banner updated."}


async def _save_channel_image(file: UploadFile, subdir: str, max_dim: int) -> str:
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(400, "Only JPEG, PNG, or WebP images allowed.")
    content = await file.read()
    if len(content) > settings.MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(400, "Image must be under 5MB.")
    try:
        img = Image.open(io.BytesIO(content))
        img.verify()
        img = Image.open(io.BytesIO(content))
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="WEBP", quality=88)
        buf.seek(0)
    except Exception:
        raise HTTPException(400, "Invalid or corrupt image.")
    save_dir = Path(settings.MEDIA_DIR) / "channels" / subdir
    save_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.webp"
    (save_dir / fname).write_bytes(buf.read())
    return f"/media/channels/{subdir}/{fname}"


def _delete_media_file(path: str):
    try:
        full = Path(settings.MEDIA_DIR) / Path(path.lstrip("/media/"))
        if full.exists():
            full.unlink()
    except Exception:
        pass


# ══ User's channel roles (for profile) ══════════════════════════════════════════

@router.get("/user/{username}/roles", response_model=list)
async def user_channel_roles(
    username: str,
    db:       AsyncSession = Depends(get_db),
):
    """Returns all channel roles for a user (for profile display)."""
    user_r = await db.execute(select(User).where(User.username == username.lower()))
    user   = user_r.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found.")

    result = await db.execute(
        select(ChannelMembership).where(
            ChannelMembership.user_id == user.id,
            ChannelMembership.role.in_([MemberRole.CHIEF_LEAD, MemberRole.LEAD]),
        )
    )
    memberships = result.scalars().all()

    out = []
    for m in memberships:
        await db.refresh(m, ["channel"])
        out.append({
            "channel_slug": m.channel.slug,
            "channel_name": m.channel.name,
            "role":         m.role,
            "title":        m.title,
            "permissions":  m.permissions,
        })
    return out


# ══ Post response builder ═════════════════════════════════════════════════════

def _serialize_user(u) -> dict:
    return {
        "id": u.id, "username": u.username,
        "display_name": u.display_name, "avatar_path": u.avatar_path,
        "bio_markdown": u.bio_markdown,
        "created_at": u.created_at.isoformat() if hasattr(u.created_at, 'isoformat') else str(u.created_at),
        "pq_public_key": u.pq_public_key,
    }


def _build_post_response(post: Post, user_vote: Optional[int]) -> dict:
    return {
        "id": post.id, "author": _serialize_user(post.author),
        "title": post.title, "body": post.body,
        "image_path": post.image_path, "link_url": post.link_url,
        "link_title": post.link_title, "link_preview": post.link_preview,
        "upvotes": post.upvotes, "downvotes": post.downvotes,
        "wilson_score": post.wilson_score,
        "created_at": post.created_at.isoformat() if hasattr(post.created_at,'isoformat') else str(post.created_at),
        "updated_at": post.updated_at.isoformat() if hasattr(post.updated_at,'isoformat') else str(post.updated_at),
        "user_vote": user_vote,
        "channel_id": post.channel_id,
        "is_pinned": post.is_pinned,
        "removed_by_lead": post.removed_by_lead,
    }
