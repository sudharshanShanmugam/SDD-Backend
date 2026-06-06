"""Request/response structured logging middleware."""
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.logging import bind_request_context, clear_request_context, get_logger

logger = get_logger(__name__)

# Paths that should not be logged (health checks, metrics, etc.)
_SKIP_PATHS = {"/health", "/metrics", "/favicon.ico"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request/response with structured fields."""

    def __init__(self, app: ASGIApp, skip_paths: set[str] | None = None) -> None:
        super().__init__(app)
        self.skip_paths = skip_paths or _SKIP_PATHS

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.skip_paths:
            return await call_next(request)

        # Generate or propagate a request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Extract user context from request state (populated by auth middleware)
        user_id: str | None = getattr(request.state, "user_id", None)
        org_id: str | None = getattr(request.state, "org_id", None)

        bind_request_context(
            request_id=request_id,
            user_id=user_id,
            org_id=org_id,
            path=request.url.path,
        )

        start = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            logger.exception("Unhandled exception", exc_info=exc)
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log_fn = logger.warning if status_code >= 400 else logger.info
            log_fn(
                "request",
                method=request.method,
                path=request.url.path,
                query=str(request.url.query),
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                user_agent=request.headers.get("user-agent", ""),
                content_type=request.headers.get("content-type", ""),
            )
            clear_request_context()
