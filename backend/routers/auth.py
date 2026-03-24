"""
All_Chat - Auth Router
Registration, login, email verification, password reset, token refresh.
"""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from core.database import get_db
from core.security import (
    hash_password, verify_password, needs_rehash,
    create_access_token, create_refresh_token, create_email_token,
    decode_token, sanitize_text, generate_secure_token
)
from core.email import send_verification_email, send_password_reset_email
from core.crypto import generate_keypair, encode_b64
from models.user import User
from schemas.schemas import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest,
    ForgotPasswordRequest, ResetPasswordRequest, VerifyEmailRequest, MessageOut
)

router = APIRouter()


@router.post("/register", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def register(
    req: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Check uniqueness (case-insensitive)
    existing = await db.execute(
        select(User).where(
            or_(User.username == req.username.lower(), User.email == req.email.lower())
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username or email already registered.")

    # Generate PQ keypair — public stored server, private returned to client ONCE
    pub_key, _priv_key = generate_keypair()
    pub_key_b64 = encode_b64(pub_key)

    user = User(
        username=req.username.lower(),
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        pq_public_key=pub_key_b64,
    )
    db.add(user)
    await db.flush()  # get user.id

    token = create_email_token(str(user.id), "email_verify")
    background_tasks.add_task(
        send_verification_email, user.email, user.username, token
    )

    return {"message": "Account created. Please check your email to verify your account."}


@router.post("/verify-email", response_model=MessageOut)
async def verify_email(req: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.token, "email_verify")
    user_id = int(payload["sub"])

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.email_verified:
        return {"message": "Email already verified."}

    user.email_verified = True
    return {"message": "Email verified successfully. You can now log in."}


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Accept username or email
    identifier = sanitize_text(req.username).lower()
    result = await db.execute(
        select(User).where(or_(User.username == identifier, User.email == identifier))
    )
    user = result.scalar_one_or_none()

    # Constant-time failure to prevent username enumeration
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled.")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")

    # Rehash if algorithm params changed
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(req.password)

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.refresh_token, "refresh")
    user_id = int(payload["sub"])

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/forgot-password", response_model=MessageOut)
async def forgot_password(
    req: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == req.email.lower()))
    user = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    if user and user.is_active:
        token = create_email_token(str(user.id), "password_reset")
        background_tasks.add_task(send_password_reset_email, user.email, user.username, token)

    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password", response_model=MessageOut)
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.token, "password_reset")
    user_id = int(payload["sub"])

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.password_hash = hash_password(req.new_password)
    return {"message": "Password reset successfully. You can now log in."}


@router.post("/resend-verify", response_model=MessageOut)
async def resend_verification(
    req: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == req.email.lower()))
    user = result.scalar_one_or_none()

    if user and not user.email_verified and user.is_active:
        token = create_email_token(str(user.id), "email_verify")
        background_tasks.add_task(send_verification_email, user.email, user.username, token)

    return {"message": "If that email is registered and unverified, a new link has been sent."}
