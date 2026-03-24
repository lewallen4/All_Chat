"""
All_Chat - Rate Limiter
Redis-backed sliding window rate limiting per IP and per user.
Falls back to allow-all if Redis is unavailable (logs warning).
"""

import time
import logging
from typing import Optional, Tuple

import redis.asyncio as redis
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None
_redis_failed = False  # avoid hammering a dead Redis


async def get_redis() -> redis.Redis:
    global _redis_client, _redis_failed
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


ROUTE_LIMITS = {
    "/api/auth/login":           (10,  60),
    "/api/auth/register":        (5,   60),
    "/api/auth/resend-verify":   (3,  300),
    "/api/auth/forgot-password": (3,  300),
    "/api/posts":                (30,  60),
    "/api/messages":             (60,  60),
    "/api/votes":                (120, 60),
    "/api/search":               (30,  60),
}
DEFAULT_LIMIT = (settings.RATE_LIMIT_GLOBAL, 60)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_rate_limit(key: str, limit: int, window: int) -> Tuple[bool, int, int]:
    """
    Sliding window rate limit.
    Returns (allowed, remaining, retry_after_seconds).
    On Redis failure, allows the request (fail-open with log).
    """
    try:
        r = await get_redis()
        now = time.time()
        window_start = now - window

        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, window + 1)
        results = await pipe.execute()

        count = results[1]

        if count >= limit:
            oldest = await r.zrange(key, 0, 0, withscores=True)
            retry_after = int(window - (now - oldest[0][1])) + 1 if oldest else window
            return False, 0, retry_after

        return True, limit - count - 1, 0

    except Exception as e:
        logger.warning(f"Rate limiter Redis error (fail-open): {e}")
        return True, limit, 0  # fail open — don't block users if Redis is down


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        limit, window = DEFAULT_LIMIT
        for route_prefix, route_limit in ROUTE_LIMITS.items():
            if path.startswith(route_prefix):
                limit, window = route_limit
                break

        ip  = get_client_ip(request)
        key = f"rl:{ip}:{path}"

        allowed, remaining, retry_after = await check_rate_limit(key, limit, window)

        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests. Please slow down."},
                headers={
                    "Retry-After":           str(retry_after),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Limit"]     = str(limit)
        return response
