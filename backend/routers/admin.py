"""
All_Chat — Admin Router
Protected by is_admin flag. Full dashboard:
  - Site-wide stats (users, posts, votes, messages, storage)
  - User management (list, search, ban, unban, promote, demote, delete)
  - Post moderation (list, search, delete, restore)
  - Comment moderation (list, delete)
  - Audit log (recent admin actions)
  - System health (DB, Redis, disk)
"""

import os
import shutil
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, text
from pydantic import BaseModel

from core.database import get_db
from core.deps import get_current_user
from core.rate_limiter import get_redis
from core.config import settings
from models.user import User
from models.post import Post
from models.vote import Vote
from models.message import Message
from models.comment import Comment
from models.follow import Follow
from models.bookmark import Bookmark
from models.notification import Notification

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Admin guard dependency ────────────────────────────────────────────────────

async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


# ── Schemas ───────────────────────────────────────────────────────────────────

class AdminUserOut(BaseModel):
    id: int
    username: str
    email: str
    display_name: Optional[str]
    avatar_path: Optional[str]
    is_active: bool
    is_admin: bool
    email_verified: bool
    created_at: datetime
    post_count: int = 0
    vote_count: int = 0

    model_config = {"from_attributes": True}


class AdminPostOut(BaseModel):
    id: int
    author_username: str
    title: Optional[str]
    body: Optional[str]
    image_path: Optional[str]
    link_url: Optional[str]
    upvotes: int
    downvotes: int
    wilson_score: float
    is_deleted: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminCommentOut(BaseModel):
    id: int
    post_id: int
    author_username: str
    body: str
    is_deleted: bool
    upvotes: int
    downvotes: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SiteStats(BaseModel):
    total_users: int
    active_users: int
    verified_users: int
    new_users_24h: int
    new_users_7d: int
    total_posts: int
    active_posts: int
    new_posts_24h: int
    total_votes: int
    total_comments: int
    total_messages: int
    total_follows: int
    total_bookmarks: int
    media_size_mb: float
    db_version: str


class HealthStatus(BaseModel):
    database: str
    redis: str
    disk_free_gb: float
    media_size_mb: float
    uptime_info: str


class AuditEntry(BaseModel):
    timestamp: datetime
    admin: str
    action: str
    target: str
    detail: str


# In-memory audit log (last 500 entries). For production, persist to DB.
_audit_log: list[dict] = []
MAX_AUDIT = 500


def _audit(admin_username: str, action: str, target: str, detail: str = ""):
    entry = {
        "timestamp": datetime.now(timezone.utc),
        "admin":     admin_username,
        "action":    action,
        "target":    target,
        "detail":    detail,
    }
    _audit_log.insert(0, entry)
    if len(_audit_log) > MAX_AUDIT:
        _audit_log.pop()
    logger.info(f"ADMIN [{admin_username}] {action} → {target} {detail}")


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=SiteStats)
async def get_stats(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    day_ago  = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    async def count(model, *filters):
        q = select(func.count()).select_from(model)
        for f in filters:
            q = q.where(f)
        return (await db.execute(q)).scalar() or 0

    total_users    = await count(User)
    active_users   = await count(User, User.is_active == True)
    verified_users = await count(User, User.email_verified == True)
    new_24h        = await count(User, User.created_at >= day_ago)
    new_7d         = await count(User, User.created_at >= week_ago)
    total_posts    = await count(Post)
    active_posts   = await count(Post, Post.is_deleted == False)
    new_posts_24h  = await count(Post, Post.created_at >= day_ago, Post.is_deleted == False)
    total_votes    = await count(Vote)
    total_comments = await count(Comment)
    total_messages = await count(Message)
    total_follows  = await count(Follow)
    total_bm       = await count(Bookmark)

    # Media size
    media_mb = 0.0
    try:
        total_bytes = sum(
            os.path.getsize(os.path.join(root, f))
            for root, _, files in os.walk(settings.MEDIA_DIR)
            for f in files
        )
        media_mb = round(total_bytes / 1024 / 1024, 2)
    except Exception:
        pass

    # DB version
    try:
        ver_res = await db.execute(text("SELECT version()"))
        db_ver = (ver_res.scalar() or "unknown").split()[0:2]
        db_version = " ".join(db_ver)
    except Exception:
        db_version = "SQLite"

    return SiteStats(
        total_users=total_users, active_users=active_users, verified_users=verified_users,
        new_users_24h=new_24h, new_users_7d=new_7d,
        total_posts=total_posts, active_posts=active_posts, new_posts_24h=new_posts_24h,
        total_votes=total_votes, total_comments=total_comments,
        total_messages=total_messages, total_follows=total_follows,
        total_bookmarks=total_bm, media_size_mb=media_mb, db_version=db_version,
    )


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthStatus)
async def get_health(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # DB
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    # Redis
    try:
        r = await get_redis()
        await r.ping()
        redis_status = "ok"
    except Exception as e:
        redis_status = f"error: {e}"

    # Disk
    disk_free = 0.0
    try:
        usage = shutil.disk_usage(settings.MEDIA_DIR)
        disk_free = round(usage.free / 1024 / 1024 / 1024, 2)
    except Exception:
        pass

    # Media size
    media_mb = 0.0
    try:
        total_bytes = sum(
            os.path.getsize(os.path.join(root, f))
            for root, _, files in os.walk(settings.MEDIA_DIR)
            for f in files
        )
        media_mb = round(total_bytes / 1024 / 1024, 2)
    except Exception:
        pass

    return HealthStatus(
        database=db_status,
        redis=redis_status,
        disk_free_gb=disk_free,
        media_size_mb=media_mb,
        uptime_info=f"Server time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    )


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=dict)
async def list_users(
    page:    int = Query(1, ge=1),
    q:       str = Query("", max_length=100),
    sort:    str = Query("created_at", pattern="^(created_at|username|post_count)$"),
    filter:  str = Query("all", pattern="^(all|active|banned|unverified|admin)$"),
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    page_size = 30
    offset    = (page - 1) * page_size

    query = select(User)

    if q:
        query = query.where(
            User.username.ilike(f"%{q}%") | User.email.ilike(f"%{q}%")
        )
    if filter == "active":
        query = query.where(User.is_active == True)
    elif filter == "banned":
        query = query.where(User.is_active == False)
    elif filter == "unverified":
        query = query.where(User.email_verified == False)
    elif filter == "admin":
        query = query.where(User.is_admin == True)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total   = (await db.execute(count_q)).scalar() or 0

    if sort == "username":
        query = query.order_by(User.username)
    else:
        query = query.order_by(desc(User.created_at))

    result = await db.execute(query.offset(offset).limit(page_size))
    users  = result.scalars().all()

    # Attach post counts
    user_ids = [u.id for u in users]
    post_counts: dict[int, int] = {}
    vote_counts: dict[int, int] = {}
    if user_ids:
        pc = await db.execute(
            select(Post.author_id, func.count(Post.id))
            .where(Post.author_id.in_(user_ids))
            .group_by(Post.author_id)
        )
        post_counts = {r[0]: r[1] for r in pc.all()}
        vc = await db.execute(
            select(Vote.user_id, func.count(Vote.id))
            .where(Vote.user_id.in_(user_ids))
            .group_by(Vote.user_id)
        )
        vote_counts = {r[0]: r[1] for r in vc.all()}

    out = []
    for u in users:
        d = {
            "id": u.id, "username": u.username, "email": u.email,
            "display_name": u.display_name, "avatar_path": u.avatar_path,
            "is_active": u.is_active, "is_admin": u.is_admin,
            "email_verified": u.email_verified,
            "created_at": u.created_at.isoformat(),
            "post_count": post_counts.get(u.id, 0),
            "vote_count": vote_counts.get(u.id, 0),
        }
        out.append(d)

    return {"users": out, "total": total, "page": page, "has_more": (offset + len(users)) < total}


@router.post("/users/{user_id}/ban", response_model=dict)
async def ban_user(
    user_id: int,
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, user_id)
    if user.is_admin:
        raise HTTPException(400, "Cannot ban another admin.")
    if user.id == admin.id:
        raise HTTPException(400, "Cannot ban yourself.")
    user.is_active = False
    await db.flush()
    _audit(admin.username, "BAN", f"user:{user.username}")
    return {"message": f"User @{user.username} banned."}


@router.post("/users/{user_id}/unban", response_model=dict)
async def unban_user(
    user_id: int,
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, user_id)
    user.is_active = True
    await db.flush()
    _audit(admin.username, "UNBAN", f"user:{user.username}")
    return {"message": f"User @{user.username} unbanned."}


@router.post("/users/{user_id}/promote", response_model=dict)
async def promote_user(
    user_id: int,
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, user_id)
    user.is_admin = True
    await db.flush()
    _audit(admin.username, "PROMOTE", f"user:{user.username}", "granted admin")
    return {"message": f"User @{user.username} promoted to admin."}


@router.post("/users/{user_id}/demote", response_model=dict)
async def demote_user(
    user_id: int,
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, user_id)
    if user.id == admin.id:
        raise HTTPException(400, "Cannot demote yourself.")
    user.is_admin = False
    await db.flush()
    _audit(admin.username, "DEMOTE", f"user:{user.username}", "revoked admin")
    return {"message": f"User @{user.username} demoted."}


@router.post("/users/{user_id}/verify-email", response_model=dict)
async def force_verify_email(
    user_id: int,
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, user_id)
    user.email_verified = True
    await db.flush()
    _audit(admin.username, "FORCE_VERIFY", f"user:{user.username}")
    return {"message": f"Email verified for @{user.username}."}


@router.delete("/users/{user_id}", response_model=dict)
async def delete_user(
    user_id: int,
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, user_id)
    if user.id == admin.id:
        raise HTTPException(400, "Cannot delete your own account.")
    if user.is_admin:
        raise HTTPException(400, "Cannot delete another admin account.")
    username = user.username
    await db.delete(user)
    await db.flush()
    _audit(admin.username, "DELETE_USER", f"user:{username}")
    return {"message": f"User @{username} and all their data deleted."}


# ── Posts ─────────────────────────────────────────────────────────────────────

@router.get("/posts", response_model=dict)
async def list_posts(
    page:       int  = Query(1, ge=1),
    q:          str  = Query("", max_length=100),
    show_deleted: bool = Query(False),
    admin:      User = Depends(require_admin),
    db:         AsyncSession = Depends(get_db),
):
    page_size = 30
    offset    = (page - 1) * page_size

    query = select(Post)
    if not show_deleted:
        query = query.where(Post.is_deleted == False)
    if q:
        query = query.where(
            Post.title.ilike(f"%{q}%") | Post.body.ilike(f"%{q}%")
        )

    count_q = select(func.count()).select_from(query.subquery())
    total   = (await db.execute(count_q)).scalar() or 0

    query  = query.order_by(desc(Post.created_at))
    result = await db.execute(query.offset(offset).limit(page_size))
    posts  = result.scalars().all()

    out = []
    for p in posts:
        await db.refresh(p, ["author"])
        out.append({
            "id": p.id, "author_username": p.author.username,
            "title": p.title, "body": (p.body or "")[:200],
            "image_path": p.image_path, "link_url": p.link_url,
            "upvotes": p.upvotes, "downvotes": p.downvotes,
            "wilson_score": p.wilson_score, "is_deleted": p.is_deleted,
            "created_at": p.created_at.isoformat(),
        })

    return {"posts": out, "total": total, "page": page, "has_more": (offset + len(posts)) < total}


@router.delete("/posts/{post_id}", response_model=dict)
async def admin_delete_post(
    post_id: int,
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Post).where(Post.id == post_id))
    post   = result.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found.")
    post.is_deleted = True
    await db.flush()
    _audit(admin.username, "DELETE_POST", f"post:{post_id}", post.title or "")
    return {"message": "Post deleted."}


@router.post("/posts/{post_id}/restore", response_model=dict)
async def admin_restore_post(
    post_id: int,
    admin:   User = Depends(require_admin),
    db:      AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Post).where(Post.id == post_id))
    post   = result.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found.")
    post.is_deleted = False
    await db.flush()
    _audit(admin.username, "RESTORE_POST", f"post:{post_id}")
    return {"message": "Post restored."}


# ── Comments ──────────────────────────────────────────────────────────────────

@router.get("/comments", response_model=dict)
async def list_comments(
    page:         int  = Query(1, ge=1),
    q:            str  = Query("", max_length=100),
    show_deleted: bool = Query(False),
    admin:        User = Depends(require_admin),
    db:           AsyncSession = Depends(get_db),
):
    page_size = 30
    offset    = (page - 1) * page_size

    query = select(Comment)
    if not show_deleted:
        query = query.where(Comment.is_deleted == False)
    if q:
        query = query.where(Comment.body.ilike(f"%{q}%"))

    count_q = select(func.count()).select_from(query.subquery())
    total   = (await db.execute(count_q)).scalar() or 0

    result   = await db.execute(query.order_by(desc(Comment.created_at)).offset(offset).limit(page_size))
    comments = result.scalars().all()

    out = []
    for c in comments:
        await db.refresh(c, ["author"])
        out.append({
            "id": c.id, "post_id": c.post_id, "author_username": c.author.username,
            "body": c.body[:300], "is_deleted": c.is_deleted,
            "upvotes": c.upvotes, "downvotes": c.downvotes,
            "created_at": c.created_at.isoformat(),
        })

    return {"comments": out, "total": total, "page": page, "has_more": (offset + len(comments)) < total}


@router.delete("/comments/{comment_id}", response_model=dict)
async def admin_delete_comment(
    comment_id: int,
    admin:      User = Depends(require_admin),
    db:         AsyncSession = Depends(get_db),
):
    result  = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(404, "Comment not found.")
    comment.is_deleted = True
    comment.body       = "[removed by moderator]"
    await db.flush()
    _audit(admin.username, "DELETE_COMMENT", f"comment:{comment_id}")
    return {"message": "Comment removed."}


# ── Audit Log ─────────────────────────────────────────────────────────────────

@router.get("/audit", response_model=dict)
async def get_audit_log(
    page:  int  = Query(1, ge=1),
    _:     User = Depends(require_admin),
):
    page_size = 50
    start = (page - 1) * page_size
    end   = start + page_size
    page_entries = _audit_log[start:end]
    return {
        "entries":  page_entries,
        "total":    len(_audit_log),
        "page":     page,
        "has_more": end < len(_audit_log),
    }


# ── Helper ────────────────────────────────────────────────────────────────────

async def _get_user_by_id(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found.")
    return user


# ── Channel Oversight ─────────────────────────────────────────────────────────

@router.get("/channels", response_model=dict)
async def admin_list_channels(
    page:  int = Query(1, ge=1),
    q:     str = Query("", max_length=100),
    admin: User = Depends(require_admin),
    db:    AsyncSession = Depends(get_db),
):
    from models.channel import Channel
    page_size = 30
    offset    = (page - 1) * page_size
    query     = select(Channel)
    if q:
        query = query.where(Channel.name.ilike(f"%{q}%") | Channel.slug.ilike(f"%{q}%"))
    total   = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result  = await db.execute(query.order_by(desc(Channel.member_count)).offset(offset).limit(page_size))
    channels = result.scalars().all()
    out = [{"id": c.id, "slug": c.slug, "name": c.name, "description": c.description,
            "member_count": c.member_count, "post_count": c.post_count,
            "is_private": c.is_private, "is_locked": c.is_locked, "is_archived": c.is_archived,
            "created_at": c.created_at.isoformat()} for c in channels]
    return {"channels": out, "total": total, "page": page, "has_more": (offset + len(out)) < total}


@router.post("/channels/{channel_id}/archive", response_model=dict)
async def admin_archive_channel(
    channel_id: int,
    admin:  User = Depends(require_admin),
    db:     AsyncSession = Depends(get_db),
):
    from models.channel import Channel
    r = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = r.scalar_one_or_none()
    if not ch: raise HTTPException(404, "Channel not found.")
    ch.is_archived = True
    await db.flush()
    _audit(admin.username, "ARCHIVE_CHANNEL", f"channel:{ch.slug}")
    return {"message": f"Channel #{ch.slug} archived."}


@router.post("/channels/{channel_id}/restore", response_model=dict)
async def admin_restore_channel(
    channel_id: int,
    admin: User = Depends(require_admin),
    db:    AsyncSession = Depends(get_db),
):
    from models.channel import Channel
    r = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = r.scalar_one_or_none()
    if not ch: raise HTTPException(404, "Channel not found.")
    ch.is_archived = False
    await db.flush()
    _audit(admin.username, "RESTORE_CHANNEL", f"channel:{ch.slug}")
    return {"message": f"Channel #{ch.slug} restored."}
