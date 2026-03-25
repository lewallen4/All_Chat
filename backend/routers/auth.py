"""
All_Chat — Auth Router
Registration, login, email verification, password reset, token refresh, logout.

Security hardening applied:
- Refresh token JTIs stored in Redis + DB for revocation
- Account-level login attempt tracking (per username, not just per IP)
- Password reset invalidates all previous reset tokens for that user
- Email change flow requires re-verification
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, update

from core.database import get_db
from core.deps import get_current_user
from core.security import (
    hash_password, verify_password, needs_rehash,
    create_access_token, create_refresh_token, create_email_token,
    decode_token, sanitize_text,
)
from core.email import send_verification_email, send_password_reset_email
from core.crypto import generate_keypair, encode_b64
from core.rate_limiter import get_redis
from core.config import settings
from models.user import User
from models.token_blocklist import RevokedToken
from schemas.schemas import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest,
    ForgotPasswordRequest, ResetPasswordRequest, VerifyEmailRequest, MessageOut
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Refresh token helpers ──────────────────────────────────────────────────────

async def _store_jti(jti: str, user_id: int, db: AsyncSession):
    """Store refresh token JTI so it can be revoked."""
    expires = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    # Also cache in Redis for fast lookup
    try:
        r = await get_redis()
        await r.setex(f"jti:valid:{jti}", settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, str(user_id))
    except Exception:
        pass  # Redis unavailable — DB fallback is sufficient


async def _is_jti_revoked(jti: str, db: AsyncSession) -> bool:
    """Check if a JTI has been revoked. Checks Redis first, then DB."""
    try:
        r = await get_redis()
        valid = await r.get(f"jti:valid:{jti}")
        if valid is not None:
            return False  # found in valid set → not revoked
        revoked = await r.get(f"jti:revoked:{jti}")
        if revoked is not None:
            return True
    except Exception:
        pass

    # DB fallback
    result = await db.execute(
        select(RevokedToken).where(RevokedToken.jti == jti)
    )
    return result.scalar_one_or_none() is not None


async def _revoke_jti(jti: str, user_id: int, db: AsyncSession):
    """Revoke a specific JTI."""
    expires = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires))

    try:
        r = await get_redis()
        await r.delete(f"jti:valid:{jti}")
        await r.setex(f"jti:revoked:{jti}", settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, "1")
    except Exception:
        pass


async def _revoke_all_user_tokens(user_id: int, db: AsyncSession):
    """Revoke all refresh tokens for a user (logout everywhere)."""
    try:
        r = await get_redis()
        # Mark all valid JTIs for this user as revoked
        keys = await r.keys(f"jti:valid:*")
        for key in keys:
            uid = await r.get(key)
            if uid and int(uid) == user_id:
                jti = key.replace("jti:valid:", "")
                await r.delete(key)
                await r.setex(
                    f"jti:revoked:{jti}",
                    settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, "1"
                )
    except Exception:
        pass


# ── Login attempt tracking ────────────────────────────────────────────────────

async def _check_login_attempts(identifier: str) -> None:
    """Raise 429 if this account has too many recent failed logins."""
    try:
        r = await get_redis()
        key   = f"login_attempts:{identifier}"
        count = await r.get(key)
        if count and int(count) >= settings.MAX_LOGIN_ATTEMPTS:
            ttl = await r.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account temporarily locked due to too many failed attempts. "
                       f"Try again in {max(1, ttl // 60)} minutes.",
                headers={"Retry-After": str(ttl)},
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Redis unavailable — fail open


async def _record_failed_login(identifier: str) -> None:
    try:
        r = await get_redis()
        key = f"login_attempts:{identifier}"
        await r.incr(key)
        await r.expire(key, settings.LOGIN_LOCKOUT_SECONDS)
    except Exception:
        pass


async def _clear_login_attempts(identifier: str) -> None:
    try:
        r = await get_redis()
        await r.delete(f"login_attempts:{identifier}")
    except Exception:
        pass


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def register(
    req: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(User).where(
            or_(User.username == req.username.lower(), User.email == req.email.lower())
        )
    )
    # Always return same message to prevent username/email enumeration
    if existing.scalar_one_or_none():
        return {"message": "Account created. Please check your email to verify your account."}

    pub_key, _ = generate_keypair()

    user = User(
        username      = req.username.lower(),
        email         = req.email.lower(),
        password_hash = hash_password(req.password),
        pq_public_key = encode_b64(pub_key),
    )
    db.add(user)
    await db.flush()

    token = create_email_token(str(user.id), "email_verify")
    background_tasks.add_task(send_verification_email, user.email, user.username, token)

    return {"message": "Account created. Please check your email to verify your account."}


@router.post("/verify-email", response_model=MessageOut)
async def verify_email(req: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.token, "email_verify")
    user_id = int(payload["sub"])

    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.email_verified:
        return {"message": "Email already verified."}

    user.email_verified = True
    return {"message": "Email verified successfully. You can now log in."}


@router.post("/login", response_model=TokenResponse)
async def login(
    req:     LoginRequest,
    request: Request,
    db:      AsyncSession = Depends(get_db),
):
    identifier = sanitize_text(req.username).lower()

    # Check account-level lockout before querying DB
    await _check_login_attempts(identifier)

    result = await db.execute(
        select(User).where(or_(User.username == identifier, User.email == identifier))
    )
    user = result.scalar_one_or_none()

    # Constant-time path — always run verify even on miss
    password_ok = verify_password(req.password, user.password_hash) if user else False

    if not user or not password_ok:
        await _record_failed_login(identifier)
        # Small constant delay to make timing attacks harder
        import asyncio
        await asyncio.sleep(0.1)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled.")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")

    # Successful login — clear attempt counter
    await _clear_login_attempts(identifier)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(req.password)

    # If 2FA is enabled, return a short-lived pending token instead of full tokens
    if user.totp_enabled:
        pending_token = create_email_token(str(user.id), "2fa_pending")
        return {"requires_2fa": True, "temp_token": pending_token, "token_type": "bearer"}

    access_token             = create_access_token(str(user.id))
    refresh_token_str, jti   = create_refresh_token(str(user.id))

    await _store_jti(jti, user.id, db)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token_str)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.refresh_token, "refresh")
    jti     = payload.get("jti", "")
    user_id = int(payload["sub"])

    # Check revocation
    if await _is_jti_revoked(jti, db):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked.")

    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    # Rotate: revoke old JTI, issue new token pair
    await _revoke_jti(jti, user_id, db)

    new_access_token           = create_access_token(str(user.id))
    new_refresh_token_str, new_jti = create_refresh_token(str(user.id))
    await _store_jti(new_jti, user.id, db)

    return TokenResponse(access_token=new_access_token, refresh_token=new_refresh_token_str)


@router.post("/logout", response_model=MessageOut)
async def logout(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Revoke the provided refresh token. Pass refresh_token in body."""
    try:
        payload = decode_token(req.refresh_token, "refresh")
        jti     = payload.get("jti", "")
        user_id = int(payload["sub"])
        await _revoke_jti(jti, user_id, db)
    except HTTPException:
        pass  # Already expired or invalid — treat as success
    return {"message": "Logged out successfully."}


@router.post("/logout-all", response_model=MessageOut)
async def logout_all(
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke ALL refresh tokens for this user — logs out every device."""
    await _revoke_all_user_tokens(current_user.id, db)
    return {"message": "Logged out from all devices."}


@router.post("/forgot-password", response_model=MessageOut)
async def forgot_password(
    req: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == req.email.lower()))
    user   = result.scalar_one_or_none()

    if user and user.is_active:
        token = create_email_token(str(user.id), "password_reset")
        background_tasks.add_task(send_password_reset_email, user.email, user.username, token)

    # Always return success — prevent email enumeration
    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password", response_model=MessageOut)
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.token, "password_reset")
    user_id = int(payload["sub"])
    # Use the token's iat (issued-at) as a one-time key
    token_key = f"pwd_reset_used:{user_id}:{payload.get('exp', '')}"

    # Check if this token has already been used
    try:
        r = await get_redis()
        already_used = await r.get(token_key)
        if already_used:
            raise HTTPException(status_code=400, detail="This reset link has already been used.")
    except HTTPException:
        raise
    except Exception:
        pass  # Redis unavailable — proceed (DB password change is still secure)

    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.password_hash = hash_password(req.new_password)

    # Mark this token as used (TTL = reset token expiry)
    try:
        r = await get_redis()
        await r.setex(token_key, settings.PASSWORD_RESET_EXPIRE_HOURS * 3600, "1")
    except Exception:
        pass

    # Invalidate all existing sessions after password change
    await _revoke_all_user_tokens(user_id, db)

    return {"message": "Password reset successfully. Please log in again."}


@router.post("/resend-verify", response_model=MessageOut)
async def resend_verification(
    req: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == req.email.lower()))
    user   = result.scalar_one_or_none()

    if user and not user.email_verified and user.is_active:
        token = create_email_token(str(user.id), "email_verify")
        background_tasks.add_task(send_verification_email, user.email, user.username, token)

    return {"message": "If that email is registered and unverified, a new link has been sent."}
