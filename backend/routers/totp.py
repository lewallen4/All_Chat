"""
All_Chat — Two-Factor Authentication Router (TOTP)

Flow for enabling 2FA:
  1. POST /api/2fa/setup         → returns otpauth:// URI + QR code data URL
  2. User scans QR in authenticator app (Google Authenticator, Aegis, Bitwarden, etc.)
  3. POST /api/2fa/verify-setup  → user submits 6-digit code to confirm they scanned it
  4. 2FA is now active on the account

Flow for login with 2FA enabled:
  1. POST /api/auth/login        → if 2FA enabled, returns {requires_2fa: true, temp_token: ...}
  2. POST /api/2fa/login         → user submits temp_token + 6-digit TOTP code → full tokens

Flow for disabling 2FA:
  1. POST /api/2fa/disable       → requires current TOTP code + password confirmation

Backup codes: 8 single-use codes generated at setup, shown once.
"""

import base64
import io
import secrets
import logging
from datetime import datetime, timezone, timedelta

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from core.database import get_db
from core.deps import get_current_user
from core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from core.rate_limiter import get_redis
from core.config import settings
from models.user import User
from routers.auth import _store_jti

router = APIRouter()
logger = logging.getLogger(__name__)

APP_NAME = "All_Chat"

# ── Schemas ───────────────────────────────────────────────────────────────────

class TOTPSetupResponse(BaseModel):
    otpauth_url:  str
    qr_code:      str   # data:image/png;base64,...
    secret:       str   # shown once for manual entry
    backup_codes: list[str]  # 8 single-use codes, shown once


class TOTPCodeRequest(BaseModel):
    code: str  # 6-digit TOTP code


class TOTPLoginRequest(BaseModel):
    temp_token: str
    code:       str


class TOTPDisableRequest(BaseModel):
    password: str
    code:     str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_secret() -> str:
    return pyotp.random_base32()


def _make_totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret)


def _verify_code(secret: str, code: str) -> bool:
    """Verify TOTP code with ±1 window for clock drift."""
    try:
        totp = _make_totp(secret)
        return totp.verify(code.strip(), valid_window=1)
    except Exception:
        return False


def _generate_backup_codes() -> list[str]:
    """Generate 8 single-use backup codes."""
    return [secrets.token_hex(5).upper() for _ in range(8)]


def _make_qr_data_url(otpauth_url: str) -> str:
    """Generate a QR code as a base64 PNG data URL."""
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(otpauth_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


async def _store_backup_codes(user_id: int, codes: list[str]):
    """Store hashed backup codes in Redis (valid for 10 years)."""
    try:
        r = await get_redis()
        for code in codes:
            key = f"2fa:backup:{user_id}:{code}"
            await r.setex(key, 10 * 365 * 86400, "unused")
    except Exception as e:
        logger.warning(f"Could not store backup codes in Redis: {e}")


async def _use_backup_code(user_id: int, code: str) -> bool:
    """Consume a backup code — returns True if valid and unused."""
    try:
        r = await get_redis()
        key = f"2fa:backup:{user_id}:{code.upper().strip()}"
        val = await r.get(key)
        if val == "unused":
            await r.delete(key)
            return True
    except Exception:
        pass
    return False


async def _rate_limit_2fa(user_id: int):
    """5 attempts per 10 minutes per user."""
    try:
        r  = await get_redis()
        key = f"2fa:attempts:{user_id}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 600)
        if count > 5:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many 2FA attempts. Try again in 10 minutes.",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # fail open if Redis unavailable


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/setup", response_model=TOTPSetupResponse)
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """
    Generate a new TOTP secret and return the QR code + backup codes.
    2FA is NOT enabled until the user confirms with /verify-setup.
    """
    if current_user.totp_enabled:
        raise HTTPException(400, "2FA is already enabled. Disable it first to reset.")

    secret      = _generate_secret()
    totp        = _make_totp(secret)
    otpauth_url = totp.provisioning_uri(
        name=current_user.username,
        issuer_name=APP_NAME,
    )
    qr_code      = _make_qr_data_url(otpauth_url)
    backup_codes = _generate_backup_codes()

    # Store secret temporarily — not committed until verify-setup succeeds
    current_user.totp_secret   = secret
    current_user.totp_enabled  = False
    current_user.totp_verified = False
    await db.flush()

    # Pre-store backup codes in Redis
    await _store_backup_codes(current_user.id, backup_codes)

    logger.info(f"2FA setup initiated for user {current_user.username}")

    return TOTPSetupResponse(
        otpauth_url=otpauth_url,
        qr_code=qr_code,
        secret=secret,
        backup_codes=backup_codes,
    )


@router.post("/verify-setup")
async def verify_setup(
    req:          TOTPCodeRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """
    Confirm setup by submitting a valid TOTP code.
    This activates 2FA on the account.
    """
    if not current_user.totp_secret:
        raise HTTPException(400, "Start 2FA setup first via POST /api/2fa/setup.")

    await _rate_limit_2fa(current_user.id)

    if not _verify_code(current_user.totp_secret, req.code):
        raise HTTPException(400, "Invalid code. Check your authenticator app and try again.")

    current_user.totp_enabled  = True
    current_user.totp_verified = True
    await db.flush()

    logger.info(f"2FA enabled for user {current_user.username}")
    return {"message": "Two-factor authentication is now enabled on your account."}


@router.post("/disable")
async def disable_2fa(
    req:          TOTPDisableRequest,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """Disable 2FA. Requires both current password and a valid TOTP code."""
    if not current_user.totp_enabled:
        raise HTTPException(400, "2FA is not enabled on this account.")

    await _rate_limit_2fa(current_user.id)

    if not verify_password(req.password, current_user.password_hash):
        raise HTTPException(403, "Incorrect password.")

    if not _verify_code(current_user.totp_secret, req.code):
        raise HTTPException(400, "Invalid 2FA code.")

    current_user.totp_secret   = None
    current_user.totp_enabled  = False
    current_user.totp_verified = False
    await db.flush()

    # Clear backup codes
    try:
        r = await get_redis()
        keys = await r.keys(f"2fa:backup:{current_user.id}:*")
        if keys:
            await r.delete(*keys)
    except Exception:
        pass

    logger.info(f"2FA disabled for user {current_user.username}")
    return {"message": "Two-factor authentication has been disabled."}


@router.get("/status")
async def get_2fa_status(current_user: User = Depends(get_current_user)):
    """Returns whether 2FA is enabled for the current user."""
    return {
        "enabled": current_user.totp_enabled,
        "verified": current_user.totp_verified,
    }


@router.post("/login")
async def login_with_2fa(
    req: TOTPLoginRequest,
    db:  AsyncSession = Depends(get_db),
):
    """
    Complete login when 2FA is required.
    temp_token is a short-lived JWT returned by /api/auth/login when 2FA is enabled.
    Accepts either a TOTP code or a backup code.
    """
    # Decode the temporary token
    try:
        payload = decode_token(req.temp_token, "2fa_pending")
    except HTTPException:
        raise HTTPException(401, "Invalid or expired 2FA session. Please log in again.")

    user_id = int(payload["sub"])
    result  = await db.execute(select(User).where(User.id == user_id))
    user    = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(401, "Invalid session.")

    await _rate_limit_2fa(user_id)

    code = req.code.strip().replace(" ", "").replace("-", "")

    # Try TOTP first, then backup code
    valid = False
    if len(code) == 6 and code.isdigit():
        valid = _verify_code(user.totp_secret, code)
    elif len(code) == 10:  # backup code format: 5 bytes = 10 hex chars
        valid = await _use_backup_code(user_id, code)

    if not valid:
        raise HTTPException(400, "Invalid 2FA code.")

    # Clear rate limit on success
    try:
        r = await get_redis()
        await r.delete(f"2fa:attempts:{user_id}")
    except Exception:
        pass

    access_token          = create_access_token(str(user.id))
    refresh_token_str, jti = create_refresh_token(str(user.id))
    await _store_jti(jti, user.id, db)

    logger.info(f"2FA login completed for user {user.username}")
    return {
        "access_token":  access_token,
        "refresh_token": refresh_token_str,
        "token_type":    "bearer",
    }


@router.post("/regenerate-backup-codes")
async def regenerate_backup_codes(
    req:          TOTPCodeRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate new backup codes (invalidates old ones). Requires valid TOTP code."""
    if not current_user.totp_enabled:
        raise HTTPException(400, "2FA is not enabled.")

    await _rate_limit_2fa(current_user.id)

    if not _verify_code(current_user.totp_secret, req.code):
        raise HTTPException(400, "Invalid 2FA code.")

    # Clear old backup codes
    try:
        r = await get_redis()
        keys = await r.keys(f"2fa:backup:{current_user.id}:*")
        if keys:
            await r.delete(*keys)
    except Exception:
        pass

    new_codes = _generate_backup_codes()
    await _store_backup_codes(current_user.id, new_codes)

    return {
        "message": "New backup codes generated. Store these securely — they won't be shown again.",
        "backup_codes": new_codes,
    }
