"""
All_Chat - Votes Router
Upvote / downvote posts. Re-votes toggle. Wilson score updated atomically.
Invalidates feed cache on vote change.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.deps import get_current_user
from core.rate_limiter import get_redis
from models.user import User
from models.post import Post
from models.vote import Vote
from schemas.schemas import VoteRequest, VoteResponse
from services.wilson import wilson_score_lower_bound

router = APIRouter()


@router.post("", response_model=VoteResponse)
async def cast_vote(
    req: VoteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Fetch post
    post_result = await db.execute(
        select(Post).where(Post.id == req.post_id, Post.is_deleted == False)
    )
    post = post_result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")

    # Prevent self-voting
    if post.author_id == current_user.id:
        raise HTTPException(status_code=403, detail="You cannot vote on your own post.")

    # Check for existing vote
    vote_result = await db.execute(
        select(Vote).where(Vote.user_id == current_user.id, Vote.post_id == req.post_id)
    )
    existing_vote = vote_result.scalar_one_or_none()

    user_vote: int | None

    if existing_vote:
        if existing_vote.value == req.value:
            # Same vote again = remove (toggle off)
            if existing_vote.value == 1:
                post.upvotes   = max(0, post.upvotes - 1)
            else:
                post.downvotes = max(0, post.downvotes - 1)
            await db.delete(existing_vote)
            user_vote = None
        else:
            # Switching vote direction
            if existing_vote.value == 1:
                post.upvotes   = max(0, post.upvotes - 1)
                post.downvotes = post.downvotes + 1
            else:
                post.downvotes = max(0, post.downvotes - 1)
                post.upvotes   = post.upvotes + 1
            existing_vote.value = req.value
            user_vote = req.value
    else:
        # New vote
        new_vote = Vote(user_id=current_user.id, post_id=req.post_id, value=req.value)
        db.add(new_vote)
        if req.value == 1:
            post.upvotes   = post.upvotes + 1
        else:
            post.downvotes = post.downvotes + 1
        user_vote = req.value

    # Recalculate Wilson score
    post.wilson_score = wilson_score_lower_bound(post.upvotes, post.downvotes)

    await db.flush()

    # Invalidate all feed caches (pattern delete)
    r = await get_redis()
    feed_keys = await r.keys("feed:*")
    if feed_keys:
        await r.delete(*feed_keys)

    return VoteResponse(
        post_id=post.id,
        upvotes=post.upvotes,
        downvotes=post.downvotes,
        wilson_score=post.wilson_score,
        user_vote=user_vote,
    )
