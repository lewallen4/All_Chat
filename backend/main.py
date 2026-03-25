"""
All_Chat — Main Application Entry Point
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.config import settings
from core.database import engine, Base
from core.security import SecurityHeadersMiddleware
from core.rate_limiter import RateLimitMiddleware
from routers import auth, users, posts, feed, votes, messages, search, media, social, admin, channels, totp

# Register all models so Base.metadata is complete
import models            # noqa: F401
import models.notification  # noqa: F401
import models.follow        # noqa: F401
import models.bookmark      # noqa: F401
import models.comment       # noqa: F401
import models.channel       # noqa: F401
import models.channel_watch  # noqa: F401
import models.comment_vote   # noqa: F401
import models.token_blocklist  # noqa: F401
import models.audit_log       # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Path resolution ────────────────────────────────────────────────────────────
_backend_dir  = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_backend_dir)

STATIC_DIR   = os.environ.get("STATIC_DIR",  os.path.join(_project_root, "frontend", "static"))
TEMPLATE_DIR = os.environ.get("TEMPLATE_DIR", os.path.join(_project_root, "frontend", "templates"))
MEDIA_DIR    = settings.MEDIA_DIR

os.makedirs(MEDIA_DIR,                          exist_ok=True)
os.makedirs(os.path.join(MEDIA_DIR, "avatars"), exist_ok=True)
os.makedirs(os.path.join(MEDIA_DIR, "posts"),   exist_ok=True)


async def _cleanup_expired_tokens():
    """Periodically delete expired revoked tokens and audit log entries older than 1 year."""
    import asyncio
    while True:
        try:
            await asyncio.sleep(3600)  # run hourly
            from datetime import datetime, timezone
            from sqlalchemy import delete
            from models.token_blocklist import RevokedToken
            from models.audit_log import AuditLog
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                year_ago = now - timedelta(days=365)
                await db.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
                # Keep audit log for 1 year
                await db.execute(delete(AuditLog).where(AuditLog.timestamp < year_ago))
                await db.commit()
        except Exception as e:
            logger.warning(f"Token cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from datetime import timedelta
    from core.database import AsyncSessionLocal
    logger.info("Starting All_Chat...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified.")
    # Start background cleanup task
    cleanup_task = asyncio.create_task(_cleanup_expired_tokens())
    yield
    cleanup_task.cancel()
    logger.info("Shutting down All_Chat...")


app = FastAPI(
    title="All_Chat",
    version="1.0.0",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Limit raw request body size (guards against payload bombs before Pydantic validation)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    MAX_BODY_SIZE = 20 * 1024 * 1024  # 20MB absolute ceiling

    async def dispatch(self, request: StarletteRequest, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large."},
            )
        return await call_next(request)

app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    expose_headers=["X-RateLimit-Remaining", "X-RateLimit-Limit", "Retry-After"],
    max_age=600,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/media",  StaticFiles(directory=MEDIA_DIR),  name="media")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

app.include_router(auth.router,     prefix="/api/auth",     tags=["auth"])
app.include_router(users.router,    prefix="/api/users",    tags=["users"])
app.include_router(posts.router,    prefix="/api/posts",    tags=["posts"])
app.include_router(feed.router,     prefix="/api/feed",     tags=["feed"])
app.include_router(votes.router,    prefix="/api/votes",    tags=["votes"])
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(search.router,   prefix="/api/search",   tags=["search"])
app.include_router(media.router,    prefix="/api/media",    tags=["media"])
app.include_router(social.router,   prefix="/api/social",   tags=["social"])
app.include_router(admin.router,    prefix="/api/admin",    tags=["admin"])
app.include_router(channels.router, prefix="/api/channels", tags=["channels"])
app.include_router(totp.router,     prefix="/api/2fa",      tags=["2fa"])

@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def serve_spa(request: Request, full_path: str):
    return templates.TemplateResponse("index.html", {"request": request})
