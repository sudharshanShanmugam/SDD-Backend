"""Tenant extraction middleware: reads JWT claims and injects org context."""
from typing import Callable, Optional

from fastapi import Request, Response
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.logging import get_logger

logger = get_logger(__name__)

# Paths that do not require a tenant context
_PUBLIC_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/auth/verify-email",
}


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Extract organization_id and user_id from the JWT access token
    and attach them to request.state so downstream handlers can use
    them without re-decoding the token.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Initialise defaults
        request.state.user_id = None
        request.state.org_id = None
        request.state.user_role = None

        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        auth_header: Optional[str] = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            try:
                from app.core.security import decode_access_token

                token_data = decode_access_token(token)
                request.state.user_id = token_data.subject
                request.state.org_id = token_data.org_id
                request.state.user_role = token_data.role
            except JWTError:
                # Token is invalid; let the route handler return 401
                pass
            except Exception as exc:
                logger.warning("Tenant middleware: unexpected error", error=str(exc))

        return await call_next(request)
