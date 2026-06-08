"""Redis-based sliding window rate limiting middleware."""
import time
from typing import Callable, Optional

import redis.asyncio as aioredis
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_redis_pool

logger = get_logger(__name__)

# Paths exempt from rate limiting
_EXEMPT_PATHS = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter using Redis sorted sets.

    Algorithm:
    1. Key = "rl:{identifier}:{window_name}"
    2. Add current timestamp to a sorted set with ZADD
    3. Remove timestamps older than the window with ZREMRANGEBYSCORE
    4. Count remaining members with ZCARD
    5. If count > limit → 429; else allow the request

    The identifier is the authenticated user ID (from request.state.user_id)
    or the client IP address for unauthenticated requests.
    """

    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.rpm = requests_per_minute
        self.rph = requests_per_hour
        self.enabled = enabled

    def _get_identifier(self, request: Request) -> str:
        user_id: Optional[str] = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return f"ip:{forwarded_for.split(',')[0].strip()}"
        return f"ip:{request.client.host if request.client else 'unknown'}"

    async def _check_limit(
        self,
        redis: aioredis.Redis,
        identifier: str,
        window_name: str,
        window_seconds: int,
        limit: int,
    ) -> tuple[bool, int, int]:
        """
        Returns (allowed, current_count, retry_after_seconds).
        Uses a Lua script for atomicity.
        """
        key = f"rl:{identifier}:{window_name}"
        now = time.time()
        window_start = now - window_seconds

        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        local expire = tonumber(ARGV[4])

        -- Remove timestamps outside the window
        redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

        -- Count current requests
        local count = redis.call('ZCARD', key)

        if count < limit then
            -- Add current request
            redis.call('ZADD', key, now, now)
            redis.call('EXPIRE', key, expire)
            return {1, count + 1}
        else
            return {0, count}
        end
        """
        result = await redis.eval(
            lua_script,
            1,
            key,
            now,
            window_start,
            limit,
            window_seconds + 1,
        )
        allowed = bool(result[0])
        count = int(result[1])
        retry_after = window_seconds if not allowed else 0
        return allowed, count, retry_after

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled or request.url.path in _EXEMPT_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        # ── Rate-limit check (Redis only) ──────────────────────────────────────
        # Keep the Redis operations isolated in try/except so that infrastructure
        # failures never prevent call_next from being called.  Critically, we must
        # NOT call call_next inside the except block — doing so would call it twice
        # (once in the happy path, once in the error path) which deadlocks Starlette's
        # BaseHTTPMiddleware body-streaming queue.
        count_m: int = 0
        try:
            pool = get_redis_pool()
            redis = aioredis.Redis(connection_pool=pool)

            identifier = self._get_identifier(request)

            # Check per-minute limit
            allowed_m, count_m, retry_m = await self._check_limit(
                redis, identifier, "minute", 60, self.rpm
            )
            if not allowed_m:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please slow down.",
                        "retry_after": retry_m,
                    },
                    headers={
                        "Retry-After": str(retry_m),
                        "X-RateLimit-Limit": str(self.rpm),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Window": "60s",
                    },
                )

            # Check per-hour limit
            allowed_h, count_h, retry_h = await self._check_limit(
                redis, identifier, "hour", 3600, self.rph
            )
            if not allowed_h:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "RATE_LIMIT_EXCEEDED",
                        "message": "Hourly rate limit exceeded.",
                        "retry_after": retry_h,
                    },
                    headers={
                        "Retry-After": str(retry_h),
                        "X-RateLimit-Limit": str(self.rph),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Window": "3600s",
                    },
                )

        except Exception as exc:
            # Redis unavailable or misconfigured — log and proceed without limiting.
            logger.warning("Rate limit check failed, allowing request", error=str(exc))

        # ── Forward request — always exactly once ────────────────────────────
        response = await call_next(request)
        if count_m:
            response.headers["X-RateLimit-Limit-Minute"] = str(self.rpm)
            response.headers["X-RateLimit-Remaining-Minute"] = str(max(0, self.rpm - count_m))
        return response
