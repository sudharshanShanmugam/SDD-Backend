"""Middleware that strips trailing slashes from API paths before routing."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class StripTrailingSlashMiddleware(BaseHTTPMiddleware):
    """Silently rewrite /foo/ → /foo so all API routes resolve regardless of trailing slash."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.scope.get("path", "")
        if path != "/" and path.endswith("/"):
            request.scope["path"] = path.rstrip("/")
            raw = request.scope.get("raw_path", b"")
            if raw:
                request.scope["raw_path"] = raw.rstrip(b"/")
        return await call_next(request)
