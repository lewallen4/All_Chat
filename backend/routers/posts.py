"""
All_Chat - Posts Router
Create, read, delete posts. Supports text, image, and link content.
"""

import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from typing import Optional
from PIL import Image

from core.database import get_db
from core.deps import get_current_user, get_current_user_optional
from core.config import settings
from core.security import sanitize_text, sanitize_html, validate_image_magic
from models.user import User
from models.post import Post
from models.vote import Vote
from models.channel import Channel, ChannelMembership, MemberRole
from schemas.schemas import PostResponse, MessageOut
from services.wilson import wilson_score_lower_bound

router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_POST_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB for post images


@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    title:        Optional[str] = Form(None),
    body:         Optional[str] = Form(None),
    link_url:     Optional[str] = Form(None),
    channel_slug: Optional[str] = Form(None),
    image:        Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    # Validate at least one field
    if not title and not body and not link_url and not image:
        raise HTTPException(status_code=400, detail="Post must have at least one content field.")

    # Sanitize inputs
    clean_title    = sanitize_text(title)[:300] if title else None
    clean_body     = sanitize_html(body)[:40000] if body else None
    clean_link     = None

    if link_url:
        link_url = link_url.strip()
        if not link_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Link must be http/https.")
        clean_link = link_url[:2048]

    # Handle image upload
    image_path = None
    if image:
        content = await image.read()
        if len(content) > MAX_POST_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="Image must be under 10MB.")
        # Validate file magic bytes — never trust Content-Type header
        validate_image_magic(content)
        try:
            img = Image.open(io.BytesIO(content))
            img.verify()
            img = Image.open(io.BytesIO(content))
            # Cap dimensions at 2048x2048
            if img.width > 2048 or img.height > 2048:
                img.thumbnail((2048, 2048), Image.LANCZOS)
            output = io.BytesIO()
            img.convert("RGB").save(output, format="WEBP", quality=88)
            output.seek(0)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupt image.")

        posts_dir = Path(settings.MEDIA_DIR) / "posts"
        posts_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{current_user.id}_{uuid.uuid4().hex}.webp"
        save_path = posts_dir / filename
        with open(save_path, "wb") as f:
            f.write(output.read())
        image_path = f"/media/posts/{filename}"

    # Resolve channel
    resolved_channel_id = None
    if channel_slug:
        from models.channel import Channel, ChannelMembership, MemberRole
        ch_r = await db.execute(
            select(Channel).where(Channel.slug == channel_slug.lower(), Channel.is_archived == False)
        )
        ch = ch_r.scalar_one_or_none()
        if not ch:
            raise HTTPException(status_code=400, detail=f"Channel '{channel_slug}' not found.")
        if ch.is_locked and not current_user.is_admin:
            raise HTTPException(status_code=403, detail="This channel is locked. No new posts allowed.")
        # Must be a member (not banned)
        ms_r = await db.execute(
            select(ChannelMembership).where(
                ChannelMembership.channel_id == ch.id,
                ChannelMembership.user_id == current_user.id,
            )
        )
        ms = ms_r.scalar_one_or_none()
        if ms and ms.role == MemberRole.BANNED:
            raise HTTPException(status_code=403, detail="You are banned from this channel.")
        if ch.is_private and not ms:
            raise HTTPException(status_code=403, detail="You must be a member to post in a private channel.")
        resolved_channel_id = ch.id
        ch.post_count += 1

    post = Post(
        author_id=current_user.id,
        title=clean_title,
        body=clean_body,
        link_url=clean_link,
        image_path=image_path,
        channel_id=resolved_channel_id,
    )
    db.add(post)
    await db.flush()

    # Update full-text search vector (PostgreSQL only — skipped on SQLite)
    try:
        await db.execute(
            text("""
                UPDATE posts SET search_vector =
                    to_tsvector('english',
                        coalesce(:title, '') || ' ' ||
                        coalesce(:body, '')
                    )
                WHERE id = :post_id
            """),
            {"title": clean_title or "", "body": clean_body or "", "post_id": post.id}
        )
    except Exception:
        pass  # SQLite does not support tsvector — full-text search uses ILIKE fallback

    await db.refresh(post, ["author"])
    return _build_response(post, None)


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Post).where(Post.id == post_id, Post.is_deleted == False)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")

    await db.refresh(post, ["author"])
    user_vote = await _get_user_vote(db, current_user, post_id)
    return _build_response(post, user_vote)


@router.delete("/{post_id}", response_model=MessageOut)
async def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Post).where(Post.id == post_id, Post.is_deleted == False)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    if post.author_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized.")

    # Soft delete — keep record for vote integrity
    post.is_deleted = True
    if post.image_path:
        path = Path(settings.MEDIA_DIR) / "posts" / Path(post.image_path).name
        if path.exists():
            path.unlink()
        post.image_path = None

    return {"message": "Post deleted."}


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_user_vote(db: AsyncSession, user: Optional[User], post_id: int) -> Optional[int]:
    if not user:
        return None
    result = await db.execute(
        select(Vote.value).where(Vote.user_id == user.id, Vote.post_id == post_id)
    )
    row = result.scalar_one_or_none()
    return row


def _build_response(post: Post, user_vote: Optional[int]) -> PostResponse:
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
    )
