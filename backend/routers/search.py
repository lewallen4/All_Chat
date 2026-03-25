"""
All_Chat - Search Router
PostgreSQL full-text search for posts and users.
Sanitized queries, ranked results, pagination.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, or_
from typing import Optional

from core.database import get_db
from core.deps import get_current_user_optional
from core.security import sanitize_text
from models.user import User
from models.post import Post
from schemas.schemas import SearchResponse, PostResponse, UserPublic

router = APIRouter()

MAX_QUERY_LENGTH = 100


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_LENGTH),
    page: int = Query(1, ge=1, le=100),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    # Sanitize and clean query
    clean_q = sanitize_text(q).strip()
    if not clean_q:
        raise HTTPException(status_code=400, detail="Search query cannot be empty.")

    # Escape special characters for tsquery
    # Split into words, join with & for AND search
    words = [w for w in clean_q.split() if len(w) >= 2]
    if not words:
        raise HTTPException(status_code=400, detail="Search query too short.")

    ts_query = " & ".join(words)
    page_size = 25
    offset = (page - 1) * page_size

    # ── Post search ──────────────────────────────────────────────────────────
    # Primary: full-text search on tsvector
    # Fallback: ILIKE on title for partial matches
    try:
        post_fts_result = await db.execute(
            text("""
                SELECT id,
                       ts_rank(search_vector, to_tsquery('english', :query)) AS rank
                FROM posts
                WHERE is_deleted = false
                  AND (
                    search_vector @@ to_tsquery('english', :query)
                    OR title ILIKE :like_query
                  )
                ORDER BY rank DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "query":      ts_query,
                "like_query": f"%{clean_q}%",
                "limit":      page_size,
                "offset":     offset,
            }
        )
        post_ids = [row[0] for row in post_fts_result.all()]
    except Exception:
        # SQLite fallback — use ILIKE only
        from sqlalchemy import select as _sel
        fb = await db.execute(
            _sel(Post.id).where(
                Post.is_deleted == False,
                _post_channel_filter,
                Post.title.ilike(f"%{clean_q}%") | Post.body.ilike(f"%{clean_q}%")
            ).limit(page_size).offset(offset)
        )
        post_ids = [row[0] for row in fb.all()]

    posts = []
    if post_ids:
        post_result = await db.execute(
            select(Post).where(Post.id.in_(post_ids))
        )
        post_map = {p.id: p for p in post_result.scalars().all()}

        for pid in post_ids:
            if pid in post_map:
                post = post_map[pid]
                await db.refresh(post, ["author"])
                user_vote = None
                if current_user:
                    from models.vote import Vote
                    vote_r = await db.execute(
                        select(Vote.value).where(
                            Vote.user_id == current_user.id,
                            Vote.post_id == pid
                        )
                    )
                    user_vote = vote_r.scalar_one_or_none()
                posts.append(PostResponse(
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
                ))

    # Total post count
    try:
        post_count_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM posts
                WHERE is_deleted = false
                  AND (
                    search_vector @@ to_tsquery('english', :query)
                    OR title ILIKE :like_query
                  )
            """),
            {"query": ts_query, "like_query": f"%{clean_q}%"}
        )
        total_posts = post_count_result.scalar() or 0
    except Exception:
        from sqlalchemy import select as _sel2, func as _f2
        cr = await db.execute(
            _sel2(_f2.count()).select_from(Post).where(
                Post.is_deleted == False,
                Post.title.ilike(f"%{clean_q}%") | Post.body.ilike(f"%{clean_q}%")
            )
        )
        total_posts = cr.scalar() or 0

    # ── User search ──────────────────────────────────────────────────────────
    user_result = await db.execute(
        select(User)
        .where(
            User.is_active == True,
            or_(
                User.username.ilike(f"%{clean_q}%"),
                User.display_name.ilike(f"%{clean_q}%"),
            )
        )
        .limit(10)
    )
    users = user_result.scalars().all()
    user_count_result = await db.execute(
        select(func.count()).select_from(User).where(
            User.is_active == True,
            or_(
                User.username.ilike(f"%{clean_q}%"),
                User.display_name.ilike(f"%{clean_q}%"),
            )
        )
    )
    total_users = user_count_result.scalar() or 0

    # ── Channel search ──────────────────────────────────────────────────────────
    from models.channel import Channel
    ch_result = await db.execute(
        select(Channel).where(
            Channel.is_archived == False,
            Channel.is_private  == False,
            or_(
                Channel.name.ilike(f"%{clean_q}%"),
                Channel.slug.ilike(f"%{clean_q}%"),
            )
        ).limit(6)
    )
    channels = ch_result.scalars().all()
    total_channels = len(channels)

    return SearchResponse(
        posts=posts,
        users=list(users),
        channels=list(channels),
        total_posts=total_posts,
        total_users=total_users,
        total_channels=total_channels,
    )
