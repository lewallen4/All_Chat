"""
All_Chat — Core Configuration
All secrets MUST come from environment variables.
Missing required secrets raise errors at startup — no silent fallbacks.
"""

from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List
import secrets
import os


class Settings(BaseSettings):
    APP_NAME:  str  = "All_Chat"
    DEBUG:     bool = False

    # SECRET_KEY — REQUIRED in production. Generates random for dev only.
    SECRET_KEY: str = ""

    # Database — REQUIRED. Default will raise a connection error if used,
    # but we explicitly guard it below.
    DATABASE_URL: str = ""

    REDIS_URL: str = "redis://localhost:6379/0"  # use redis://:password@host:port/db if Redis has AUTH

    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS:   int = 30
    ALGORITHM:                   str = "HS256"

    # Email
    SMTP_HOST:     str  = "localhost"
    SMTP_PORT:     int  = 587
    SMTP_USER:     str  = ""
    SMTP_PASSWORD: str  = ""
    SMTP_FROM:     str  = "noreply@allchat.local"
    SMTP_TLS:      bool = True

    # Media
    MEDIA_DIR:           str = "/app/media"
    MAX_IMAGE_SIZE_BYTES: int = 5 * 1024 * 1024
    MAX_AVATAR_PIXELS:    int = 100

    # Security
    ALLOWED_ORIGINS:            List[str] = ["http://localhost"]
    EMAIL_VERIFY_EXPIRE_HOURS:  int = 24
    PASSWORD_RESET_EXPIRE_HOURS: int = 2

    # Login brute-force protection
    MAX_LOGIN_ATTEMPTS:    int = 10   # per window
    LOGIN_LOCKOUT_SECONDS: int = 900  # 15 minutes

    # Rate limits
    RATE_LIMIT_AUTH:     int = 10
    RATE_LIMIT_POSTS:    int = 30
    RATE_LIMIT_MESSAGES: int = 60
    RATE_LIMIT_GLOBAL:   int = 300

    # Feed
    FEED_PAGE_SIZE: int = 25
    FEED_CACHE_TTL: int = 60

    # Post-Quantum
    PQ_ENABLED: bool = True

    @field_validator("SECRET_KEY")
    @classmethod
    def require_secret_key(cls, v):
        if not v:
            # Generate a random one for development — warn loudly
            import logging
            logging.getLogger(__name__).warning(
                "SECRET_KEY not set in .env — using random key. "
                "All sessions will be lost on restart. Set SECRET_KEY in production!"
            )
            return secrets.token_urlsafe(64)
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters.")
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def require_database_url(cls, v):
        if not v:
            raise ValueError(
                "DATABASE_URL is not set. "
                "Add it to /app/backend/.env before starting."
            )
        # Reject the old default with changeme password
        if "changeme" in v:
            raise ValueError(
                "DATABASE_URL still contains 'changeme'. "
                "Set a real database password in .env."
            )
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
