"""
All_Chat — Security Module
Argon2id password hashing, JWT tokens, file magic validation,
security headers, input sanitization.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets
import hashlib
import struct

from fastapi import HTTPException, status, Request
from starlette.middleware.base import BaseHTTPMiddleware
from jose import JWTError, jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from core.config import settings

# ── Argon2id ──────────────────────────────────────────────────────────────────
# OWASP recommended. 64MB memory, parallelism 4, 3 iterations.
ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# ── Security headers ──────────────────────────────────────────────────────────
# HSTS is omitted here — nginx adds it only when TLS is active.
# Sending HSTS over plain HTTP permanently breaks sites for users.
# HSTS intentionally omitted — nginx adds it only when TLS is active.
# Sending HSTS over plain HTTP permanently breaks sites for users.
SECURITY_HEADERS = {
    "X-Content-Type-Options":            "nosniff",
    "X-Frame-Options":                   "DENY",
    "X-XSS-Protection":                  "1; mode=block",
    "Referrer-Policy":                   "strict-origin-when-cross-origin",
    "Permissions-Policy":                "camera=(), microphone=(), geolocation=()",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Cross-Origin-Opener-Policy":        "same-origin",
    # CSP: unsafe-inline removed from script-src.
    # All inline event handlers have been migrated to addEventListener() + data-action delegation.
    # style-src retains unsafe-inline because the SPA uses dynamic inline styles for transitions/themes.
    # To remove that too: migrate to CSS classes only.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "media-src 'self'; "
        "connect-src 'self'; "
        "worker-src 'none'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none';"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


# ── Password ──────────────────────────────────────────────────────────────────

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


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(subject: str, extra: dict = None) -> str:
    expire  = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "access", **(extra or {})}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> tuple[str, str]:
    """Returns (token_string, jti) — caller must store jti for revocation."""
    jti     = secrets.token_hex(32)
    expire  = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh", "jti": jti}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM), jti


def create_email_token(subject: str, purpose: str) -> str:
    expire  = datetime.now(timezone.utc) + timedelta(hours=settings.EMAIL_VERIFY_EXPIRE_HOURS)
    payload = {"sub": subject, "exp": expire, "type": purpose}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid token type")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")


def get_token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("access_token")


# ── File magic byte validation ────────────────────────────────────────────────
# Never trust Content-Type from the client.
# Check actual file signatures before passing to Pillow.

IMAGE_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff",                     "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n",               "image/png"),
    (b"RIFF????WEBP",                     "image/webp"),  # checked with mask
    (b"GIF87a",                           "image/gif"),
    (b"GIF89a",                           "image/gif"),
]


def validate_image_magic(data: bytes) -> str:
    """
    Validate file magic bytes and return detected MIME type.
    Raises HTTPException(400) if not a recognised image format.
    """
    if len(data) < 12:
        raise HTTPException(status_code=400, detail="File too small to be a valid image.")

    # JPEG
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    # PNG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    # GIF
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    # WebP: RIFF????WEBP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    raise HTTPException(
        status_code=400,
        detail="File does not appear to be a valid image (JPEG, PNG, WebP, or GIF)."
    )


# ── HTML sanitisation ─────────────────────────────────────────────────────────

import bleach

ALLOWED_TAGS = [
    "p", "br", "strong", "em", "u", "s", "blockquote", "code", "pre",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "a", "img",
]
ALLOWED_ATTRIBUTES = {
    "a":   ["href", "title", "rel"],
    "img": ["src", "alt", "width", "height"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_html(raw: str) -> str:
    return bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )


def sanitize_text(raw: str) -> str:
    return bleach.clean(raw, tags=[], strip=True).strip()


# ── Secure token ──────────────────────────────────────────────────────────────

def generate_secure_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def constant_time_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(
        hashlib.sha256(a.encode()).digest(),
        hashlib.sha256(b.encode()).digest(),
    )


# ── Secure cookie settings ────────────────────────────────────────────────────

def secure_cookie_params(is_https: bool = False) -> dict:
    """
    Returns kwargs for Response.set_cookie() with secure defaults.
    Use is_https=True when TLS is active.
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "secure":   is_https,   # True only when served over HTTPS
        "path":     "/",
    }
