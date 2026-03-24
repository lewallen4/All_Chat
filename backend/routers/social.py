"""
All_Chat — Social Router
Follow/unfollow users, bookmarks, notifications, comments.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, desc
from pydantic import BaseModel, field_validator

from core.database import get_db
from core.deps import get_current_user, get_current_user_optional
from core.security import sanitize_html, sanitize_text
from models.user import User
from models.follow import Follow
from models.bookmark import Bookmark
from models.notification import Notification
from models.comment import Comment
from models.post import Post
from models.vote import Vote
from schemas.schemas import UserPublic, PostResponse, MessageOut
from services.wilson import wilson_score_lower_bound

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class CommentCreate(BaseModel):
    post_id:   int
    body:      str
    parent_id: Optional[int] = None

    @field_validator("body")
    @classmethod
    def validate_body(cls, v):
        v = sanitize_html(v)
        if len(v) < 1:   raise ValueError("Comment cannot be empty.")
        if len(v) > 5000: raise ValueError("Comment too long (max 5,000 chars).")
        return v


class CommentResponse(BaseModel):
    id:           int
    post_id:      int
    author:       UserPublic
    body:         str
    parent_id:    Optional[int]
    upvotes:      int
    downvotes:    int
    wilson_score: float
    created_at:   datetime
    is_deleted:   bool
    user_vote:    Optional[int] = None
    replies:      list["CommentResponse"] = []

    model_config = {"from_attributes": True}

CommentResponse.model_rebuild()


class NotificationOut(BaseModel):
    id:         int
    kind:       str
    body:       Optional[str]
    is_read:    bool
    created_at: datetime
    actor:      Optional[UserPublic]
    post_id:    Optional[int]

    model_config = {"from_attributes": True}


# ── Follow ────────────────────────────────────────────────────────────────────

@router.post("/follow/{username}", response_model=MessageOut)
async def follow_user(
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _get_user(db, username)
    if target.id == current_user.id:
        raise HTTPException(400, "You cannot follow yourself.")

    existing = await db.execute(
        select(Follow).where(Follow.follower_id == current_user.id, Follow.following_id == target.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Already following.")

    db.add(Follow(follower_id=current_user.id, following_id=target.id))

    # Notify the followed user
    db.add(Notification(
        user_id=target.id, actor_id=current_user.id, kind="follow",
        body=f"{current_user.username} started following you."
    ))
    await db.flush()
    return {"message": f"Now following {target.username}."}


@router.delete("/follow/{username}", response_model=MessageOut)
async def unfollow_user(
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _get_user(db, username)
    result = await db.execute(
        select(Follow).where(Follow.follower_id == current_user.id, Follow.following_id == target.id)
    )
    follow = result.scalar_one_or_none()
    if not follow:
        raise HTTPException(400, "Not following this user.")
    await db.delete(follow)
    return {"message": f"Unfollowed {target.username}."}


@router.get("/follow/{username}/status")
async def follow_status(
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _get_user(db, username)
    r = await db.execute(
        select(Follow).where(Follow.follower_id == current_user.id, Follow.following_id == target.id)
    )
    is_following = r.scalar_one_or_none() is not None
    followers = await db.execute(select(func.count()).select_from(Follow).where(Follow.following_id == target.id))
    following = await db.execute(select(func.count()).select_from(Follow).where(Follow.follower_id == target.id))
    return {
        "is_following": is_following,
        "followers_count": followers.scalar(),
        "following_count": following.scalar(),
    }


@router.get("/following/feed", response_model=list[PostResponse])
async def following_feed(
    page: int = Query(1, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Posts from users the current user follows, sorted by newest."""
    following_ids_r = await db.execute(
        select(Follow.following_id).where(Follow.follower_id == current_user.id)
    )
    ids = [r[0] for r in following_ids_r.all()]
    if not ids:
        return []

    page_size = 25
    result = await db.execute(
        select(Post)
        .where(Post.author_id.in_(ids), Post.is_deleted == False)
        .order_by(desc(Post.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    posts = result.scalars().all()
    out = []
    for post in posts:
        await db.refresh(post, ["author"])
        vote_r = await db.execute(select(Vote.value).where(Vote.user_id == current_user.id, Vote.post_id == post.id))
        user_vote = vote_r.scalar_one_or_none()
        out.append(PostResponse(
            id=post.id, author=post.author, title=post.title, body=post.body,
            image_path=post.image_path, link_url=post.link_url, link_title=post.link_title,
            link_preview=post.link_preview, upvotes=post.upvotes, downvotes=post.downvotes,
            wilson_score=post.wilson_score, created_at=post.created_at, updated_at=post.updated_at,
            user_vote=user_vote,
        ))
    return out


# ── Bookmarks ─────────────────────────────────────────────────────────────────

@router.post("/bookmarks/{post_id}", response_model=MessageOut)
async def bookmark_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post_r = await db.execute(select(Post).where(Post.id == post_id, Post.is_deleted == False))
    if not post_r.scalar_one_or_none():
        raise HTTPException(404, "Post not found.")

    existing = await db.execute(
        select(Bookmark).where(Bookmark.user_id == current_user.id, Bookmark.post_id == post_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Already bookmarked.")

    db.add(Bookmark(user_id=current_user.id, post_id=post_id))
    return {"message": "Post bookmarked."}


@router.delete("/bookmarks/{post_id}", response_model=MessageOut)
async def remove_bookmark(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Bookmark).where(Bookmark.user_id == current_user.id, Bookmark.post_id == post_id)
    )
    bm = r.scalar_one_or_none()
    if not bm:
        raise HTTPException(404, "Bookmark not found.")
    await db.delete(bm)
    return {"message": "Bookmark removed."}


@router.get("/bookmarks", response_model=list[PostResponse])
async def get_bookmarks(
    page: int = Query(1, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    page_size = 25
    bm_r = await db.execute(
        select(Bookmark.post_id)
        .where(Bookmark.user_id == current_user.id)
        .order_by(desc(Bookmark.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    post_ids = [r[0] for r in bm_r.all()]
    if not post_ids:
        return []

    posts_r = await db.execute(select(Post).where(Post.id.in_(post_ids), Post.is_deleted == False))
    post_map = {p.id: p for p in posts_r.scalars().all()}
    out = []
    for pid in post_ids:
        if pid in post_map:
            post = post_map[pid]
            await db.refresh(post, ["author"])
            vote_r = await db.execute(select(Vote.value).where(Vote.user_id == current_user.id, Vote.post_id == pid))
            out.append(PostResponse(
                id=post.id, author=post.author, title=post.title, body=post.body,
                image_path=post.image_path, link_url=post.link_url, link_title=post.link_title,
                link_preview=post.link_preview, upvotes=post.upvotes, downvotes=post.downvotes,
                wilson_score=post.wilson_score, created_at=post.created_at, updated_at=post.updated_at,
                user_vote=vote_r.scalar_one_or_none(),
            ))
    return out


# ── Notifications ─────────────────────────────────────────────────────────────

@router.get("/notifications", response_model=list[NotificationOut])
async def get_notifications(
    page: int = Query(1, ge=1),
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        q = q.where(Notification.is_read == False)
    q = q.order_by(desc(Notification.created_at)).offset((page - 1) * 25).limit(25)
    result = await db.execute(q)
    notifs = result.scalars().all()
    for n in notifs:
        if n.actor_id:
            await db.refresh(n, ["actor"])
    return notifs


@router.post("/notifications/mark-read", response_model=MessageOut)
async def mark_notifications_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        )
    )
    notifs = result.scalars().all()
    for n in notifs:
        n.is_read = True
    return {"message": f"Marked {len(notifs)} notifications as read."}


@router.get("/notifications/count")
async def notification_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        )
    )
    return {"unread": r.scalar()}


# ── Comments ──────────────────────────────────────────────────────────────────

@router.get("/comments/{post_id}", response_model=list[CommentResponse])
async def get_comments(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Top-level comments with nested replies (2 levels)."""
    result = await db.execute(
        select(Comment)
        .where(Comment.post_id == post_id, Comment.parent_id == None)
        .order_by(desc(Comment.wilson_score), desc(Comment.created_at))
        .limit(200)
    )
    comments = result.scalars().all()
    out = []
    for c in comments:
        await db.refresh(c, ["author", "replies"])
        out.append(await _build_comment(db, c, current_user))
    return out


@router.post("/comments", response_model=CommentResponse, status_code=201)
async def create_comment(
    req: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    post_r = await db.execute(select(Post).where(Post.id == req.post_id, Post.is_deleted == False))
    post = post_r.scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found.")

    if req.parent_id:
        parent_r = await db.execute(select(Comment).where(Comment.id == req.parent_id))
        if not parent_r.scalar_one_or_none():
            raise HTTPException(404, "Parent comment not found.")

    comment = Comment(
        post_id=req.post_id,
        author_id=current_user.id,
        parent_id=req.parent_id,
        body=req.body,
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment, ["author"])

    # Notify post author if it's not the same person
    if post.author_id != current_user.id:
        db.add(Notification(
            user_id=post.author_id, actor_id=current_user.id, kind="comment",
            post_id=post.id,
            body=f"{current_user.username} commented on your post."
        ))

    return await _build_comment(db, comment, current_user)


@router.delete("/comments/{comment_id}", response_model=MessageOut)
async def delete_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = r.scalar_one_or_none()
    if not comment:
        raise HTTPException(404, "Comment not found.")
    if comment.author_id != current_user.id and not current_user.is_admin:
        raise HTTPException(403, "Not authorized.")
    comment.is_deleted = True
    comment.body = "[deleted]"
    return {"message": "Comment deleted."}


@router.post("/comments/{comment_id}/vote", response_model=dict)
async def vote_comment(
    comment_id: int,
    value: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from models.comment_vote import CommentVote
    if value not in (1, -1):
        raise HTTPException(400, "Vote value must be +1 or -1.")
    r = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = r.scalar_one_or_none()
    if not comment:
        raise HTTPException(404, "Comment not found.")
    if comment.author_id == current_user.id:
        raise HTTPException(403, "Cannot vote on your own comment.")

    existing_r = await db.execute(
        select(CommentVote).where(
            CommentVote.user_id    == current_user.id,
            CommentVote.comment_id == comment_id,
        )
    )
    existing = existing_r.scalar_one_or_none()
    user_vote: Optional[int]

    if existing:
        if existing.value == value:
            # Toggle off
            if existing.value == 1: comment.upvotes   = max(0, comment.upvotes - 1)
            else:                   comment.downvotes  = max(0, comment.downvotes - 1)
            await db.delete(existing)
            user_vote = None
        else:
            # Switch direction
            if existing.value == 1:
                comment.upvotes   = max(0, comment.upvotes - 1)
                comment.downvotes = comment.downvotes + 1
            else:
                comment.downvotes = max(0, comment.downvotes - 1)
                comment.upvotes   = comment.upvotes + 1
            existing.value = value
            user_vote = value
    else:
        db.add(CommentVote(user_id=current_user.id, comment_id=comment_id, value=value))
        if value == 1: comment.upvotes   += 1
        else:          comment.downvotes += 1
        user_vote = value

    comment.wilson_score = wilson_score_lower_bound(comment.upvotes, comment.downvotes)
    await db.flush()
    return {
        "comment_id":   comment_id,
        "upvotes":      comment.upvotes,
        "downvotes":    comment.downvotes,
        "wilson_score": comment.wilson_score,
        "user_vote":    user_vote,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_user(db: AsyncSession, username: str) -> User:
    clean = sanitize_text(username).lower()
    r = await db.execute(select(User).where(User.username == clean, User.is_active == True))
    u = r.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User not found.")
    return u


async def _build_comment(db: AsyncSession, c: Comment, current_user: Optional[User]) -> CommentResponse:
    from models.comment_vote import CommentVote

    async def get_user_vote(comment_id: int) -> Optional[int]:
        if not current_user:
            return None
        vr = await db.execute(
            select(CommentVote.value).where(
                CommentVote.user_id    == current_user.id,
                CommentVote.comment_id == comment_id,
            )
        )
        return vr.scalar_one_or_none()

    replies = []
    if c.replies:
        for reply in sorted(c.replies, key=lambda r: r.created_at):
            await db.refresh(reply, ["author"])
            reply_vote = await get_user_vote(reply.id)
            replies.append(CommentResponse(
                id=reply.id, post_id=reply.post_id, author=reply.author,
                body=reply.body if not reply.is_deleted else "[deleted]",
                parent_id=reply.parent_id, upvotes=reply.upvotes, downvotes=reply.downvotes,
                wilson_score=reply.wilson_score, created_at=reply.created_at,
                is_deleted=reply.is_deleted, user_vote=reply_vote,
            ))

    user_vote = await get_user_vote(c.id)

    return CommentResponse(
        id=c.id, post_id=c.post_id, author=c.author,
        body=c.body if not c.is_deleted else "[deleted]",
        parent_id=c.parent_id, upvotes=c.upvotes, downvotes=c.downvotes,
        wilson_score=c.wilson_score, created_at=c.created_at,
        is_deleted=c.is_deleted, user_vote=user_vote, replies=replies,
    )
