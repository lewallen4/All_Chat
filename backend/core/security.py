"""
All_Chat - Security Module
Argon2id password hashing, JWT tokens, CSRF protection, security headers.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import secrets
import hashlib

from fastapi import HTTPException, status, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from jose import JWTError, jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from core.config import settings

# Argon2id — OWASP recommended, stronger than bcrypt
ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# CSRF-exempt paths (API endpoints using Bearer tokens are safe)
CSRF_EXEMPT_PREFIXES = ["/api/", "/static/", "/media/"]

# Security headers to apply to all responses
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "  # tighten after nonce implementation
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


# ─── Password ────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        ph.verify(hashed, plain)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return ph.check_needs_rehash(hashed)


def validate_password_strength(password: str) -> list[str]:
    """Return list of violations; empty = valid."""
    errors = []
    if len(password) < 10:
        errors.append("Password must be at least 10 characters.")
    if not any(c.isupper() for c in password):
        errors.append("Password must contain an uppercase letter.")
    if not any(c.islower() for c in password):
        errors.append("Password must contain a lowercase letter.")
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain a digit.")
    if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        errors.append("Password must contain a special character.")
    return errors


# ─── JWT ─────────────────────────────────────────────────────────────────────

def create_access_token(subject: str, extra: dict = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "access", **(extra or {})}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh", "jti": secrets.token_hex(16)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_email_token(subject: str, purpose: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.EMAIL_VERIFY_EXPIRE_HOURS)
    payload = {"sub": subject, "exp": expire, "type": purpose}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


# ─── Token extraction ─────────────────────────────────────────────────────────

def get_token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # Also check cookie (for SSR pages)
    return request.cookies.get("access_token")


# ─── Sanitization ────────────────────────────────────────────────────────────

import bleach

ALLOWED_TAGS = [
    "p", "br", "strong", "em", "u", "s", "blockquote", "code", "pre",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "a", "img",
]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "width", "height"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_html(raw: str) -> str:
    """Strip dangerous HTML, allow safe subset."""
    return bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )


def sanitize_text(raw: str) -> str:
    """Strip all HTML tags for plain text fields."""
    return bleach.clean(raw, tags=[], strip=True).strip()


# ─── Secure token generation ─────────────────────────────────────────────────

def generate_secure_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def constant_time_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(
        hashlib.sha256(a.encode()).digest(),
        hashlib.sha256(b.encode()).digest(),
    )
