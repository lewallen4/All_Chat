"""
All_Chat - Core Configuration
All secrets come from environment variables. Never hardcode.
"""

from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
    # App
    APP_NAME: str = "All_Chat"
    DEBUG: bool = False
    SECRET_KEY: str = secrets.token_urlsafe(64)

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://allchat:changeme@localhost:5432/allchat"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALGORITHM: str = "HS256"

    # Email
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@allchat.local"
    SMTP_TLS: bool = True

    # Media
    MEDIA_DIR: str = "/app/media"
    MAX_IMAGE_SIZE_BYTES: int = 5 * 1024 * 1024  # 5MB
    MAX_AVATAR_PIXELS: int = 100  # 100x100 max

    # Security
    ALLOWED_ORIGINS: List[str] = ["https://allchat.local"]
    BCRYPT_ROUNDS: int = 12
    EMAIL_VERIFY_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_EXPIRE_HOURS: int = 2

    # Rate limits (requests per window)
    RATE_LIMIT_AUTH: int = 10       # per minute
    RATE_LIMIT_POSTS: int = 30      # per minute
    RATE_LIMIT_MESSAGES: int = 60   # per minute
    RATE_LIMIT_GLOBAL: int = 300    # per minute

    # Feed
    FEED_PAGE_SIZE: int = 25
    FEED_CACHE_TTL: int = 60        # seconds

    # Post-Quantum (Kyber-768 via liboqs)
    PQ_ENABLED: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
