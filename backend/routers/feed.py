"""
All_Chat - Feed Router
Sorted feed: chronological, top all-time, top by period (24h/week/month/year).
Redis-cached. Wilson score for vote ranking.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select as _s  # already imported
import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_

from core.database import get_db
from core.deps import get_current_user_optional
from core.rate_limiter import get_redis
from core.config import settings
from models.user import User
from models.post import Post
from models.vote import Vote
from schemas.schemas import FeedResponse, PostResponse

router = APIRouter()

SORT_OPTIONS = {"new", "top", "hot"}
PERIOD_OPTIONS = {"24h", "week", "month", "year", "all"}


@router.get("", response_model=FeedResponse)
async def get_feed(
    sort:         str  = Query("new", pattern="^(new|top|hot)$"),
    period:       str  = Query("all", pattern="^(24h|week|month|year|all)$"),
    page:         int  = Query(1, ge=1, le=1000),
    channel_slug: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db:           AsyncSession = Depends(get_db),
):
    page_size = settings.FEED_PAGE_SIZE
    offset = (page - 1) * page_size

    # Try cache for unauthenticated requests
    cache_key = f"feed:{sort}:{period}:{page}"
    if not current_user:
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            data = json.loads(cached)
            return FeedResponse(**data)

    # Build time filter
    time_filter = _get_time_filter(period)

    # Build query
    query = select(Post).where(Post.is_deleted == False)
    if channel_slug:
        from models.channel import Channel
        ch_r = await db.execute(select(Channel).where(Channel.slug == channel_slug))
        ch   = ch_r.scalar_one_or_none()
        if ch:
            query = query.where(Post.channel_id == ch.id)
    if time_filter is not None:
        query = query.where(Post.created_at >= time_filter)

    # Apply sort
    if sort == "new":
        query = query.order_by(desc(Post.created_at))
    elif sort == "top":
        query = query.order_by(desc(Post.wilson_score), desc(Post.created_at))
    elif sort == "hot":
        # Hot = high recent votes weighted by recency
        query = query.order_by(desc(Post.wilson_score), desc(Post.upvotes), desc(Post.created_at))

    # Count total (for pagination)
    count_query = select(Post).where(Post.is_deleted == False)
    if time_filter is not None:
        count_query = count_query.where(Post.created_at >= time_filter)

    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count()).select_from(count_query.subquery())
    )
    total = count_result.scalar()

    # Paginate
    result = await db.execute(query.offset(offset).limit(page_size))
    posts = result.scalars().all()

    # Eagerly load authors
    post_responses = []
    for post in posts:
        await db.refresh(post, ["author"])
        user_vote = await _get_user_vote(db, current_user, post.id) if current_user else None
        # Attach channel info if post belongs to a channel
        channel_info = None
        if post.channel_id:
            from models.channel import Channel as Ch
            ch_r = await db.execute(select(Ch).where(Ch.id == post.channel_id))
            ch_obj = ch_r.scalar_one_or_none()
            if ch_obj:
                channel_info = {"slug": ch_obj.slug, "name": ch_obj.name, "avatar_path": ch_obj.avatar_path}
        post_responses.append(_build_post_response(post, user_vote, channel_info))

    response_data = FeedResponse(
        posts=post_responses,
        total=total,
        page=page,
        has_more=(offset + len(posts)) < total,
    )

    # Cache for unauthenticated users
    if not current_user:
        r = await get_redis()
        await r.setex(cache_key, settings.FEED_CACHE_TTL, response_data.model_dump_json())

    return response_data


def _get_time_filter(period: str) -> Optional[datetime]:
    now = datetime.now(timezone.utc)
    mapping = {
        "24h":   now - timedelta(hours=24),
        "week":  now - timedelta(weeks=1),
        "month": now - timedelta(days=30),
        "year":  now - timedelta(days=365),
        "all":   None,
    }
    return mapping.get(period)


async def _get_user_vote(db: AsyncSession, user: User, post_id: int) -> Optional[int]:
    from sqlalchemy import select
    result = await db.execute(
        select(Vote.value).where(Vote.user_id == user.id, Vote.post_id == post_id)
    )
    return result.scalar_one_or_none()


def _build_post_response(post: Post, user_vote: Optional[int], channel_info=None) -> PostResponse:
    return PostResponse(
        id=post.id,
        author=post.author,
        title=post.title,
        body=post.body,
        image_path=post.image_path,
        link_url=post.link_url,
        link_title=post.link_title,
        link_preview=post.link_preview,
        upvotes=post.upvotes,
        downvotes=post.downvotes,
        wilson_score=post.wilson_score,
        created_at=post.created_at,
        updated_at=post.updated_at,
        user_vote=user_vote,
        channel_id=getattr(post, "channel_id", None),
        channel=channel_info,
        is_pinned=getattr(post, "is_pinned", False),
        removed_by_lead=getattr(post, "removed_by_lead", False),
    )
