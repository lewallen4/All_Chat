"""
All_Chat - Users Router
Profile viewing, editing, avatar upload, public key registration.
"""

import io
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from PIL import Image

from core.database import get_db
from core.deps import get_current_user
from core.config import settings
from core.security import sanitize_text, sanitize_html, validate_image_magic
from core.crypto import encode_b64, decode_b64
from models.user import User
from schemas.schemas import UserPublic, UserPublicWithKey, UserPrivate, UpdateProfileRequest, RegisterPublicKeyRequest, MessageOut

router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.get("/me", response_model=UserPrivate)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/{username}", response_model=UserPublicWithKey)
async def get_user_profile(username: str, db: AsyncSession = Depends(get_db)):
    clean_username = sanitize_text(username).lower()
    result = await db.execute(select(User).where(User.username == clean_username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.patch("/me/profile", response_model=UserPrivate)
async def update_profile(
    req: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.display_name is not None:
        current_user.display_name = sanitize_text(req.display_name)[:64]
    if req.bio_markdown is not None:
        # Sanitise bio — allow safe markdown-like content but strip dangerous HTML
        current_user.bio_markdown = sanitize_html(req.bio_markdown)[:2000]
    await db.flush()
    return current_user


@router.post("/me/avatar", response_model=MessageOut)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()

    # Enforce size limit before any processing
    if len(content) > settings.MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Image must be under 5MB.")

    # Validate actual file magic bytes — never trust Content-Type header
    validate_image_magic(content)

    # Validate and process image with Pillow (strips EXIF, enforces dimensions)
    try:
        img = Image.open(io.BytesIO(content))
        img.verify()
        img = Image.open(io.BytesIO(content))  # re-open after verify

        # Enforce max avatar dimensions
        max_px = settings.MAX_AVATAR_PIXELS
        if img.width > max_px or img.height > max_px:
            img.thumbnail((max_px, max_px), Image.LANCZOS)

        # Convert to RGB (strip alpha for JPEG compatibility)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        # Save as WebP for efficiency (strips EXIF automatically)
        output = io.BytesIO()
        save_mode = "RGBA" if img.mode == "RGBA" else "RGB"
        img = img.convert(save_mode)
        img.save(output, format="WEBP", quality=85)
        output.seek(0)

    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or corrupt image file.")

    # Delete old avatar
    if current_user.avatar_path:
        # Sanitise: only take the filename, never allow path traversal
        safe_name = Path(current_user.avatar_path).name
        old_path  = Path(settings.MEDIA_DIR) / "avatars" / safe_name
        # Verify the resolved path stays within the media directory
        try:
            old_path.resolve().relative_to(Path(settings.MEDIA_DIR).resolve())
            if old_path.exists():
                old_path.unlink()
        except ValueError:
            pass  # path traversal attempt — silently skip

    # Save new avatar
    avatars_dir = Path(settings.MEDIA_DIR) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{current_user.id}_{uuid.uuid4().hex}.webp"
    save_path = avatars_dir / filename

    with open(save_path, "wb") as f:
        f.write(output.read())

    current_user.avatar_path = f"/media/avatars/{filename}"
    await db.flush()

    return {"message": "Avatar updated successfully."}


@router.post("/me/public-key", response_model=MessageOut)
async def register_public_key(
    req: RegisterPublicKeyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register or update the user's PQ public key for E2E DM encryption."""
    # Validate it's valid base64
    try:
        key_bytes = decode_b64(req.public_key)
        if len(key_bytes) < 32:
            raise ValueError("Key too short.")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid public key format.")

    current_user.pq_public_key = req.public_key
    await db.flush()
    return {"message": "Public key registered."}


@router.delete("/me/avatar", response_model=MessageOut)
async def delete_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.avatar_path:
        path = Path(settings.MEDIA_DIR) / "avatars" / Path(current_user.avatar_path).name
        if path.exists():
            path.unlink()
        current_user.avatar_path = None
        await db.flush()
    return {"message": "Avatar removed."}
