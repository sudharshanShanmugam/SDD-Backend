"""Audit middleware: intercept mutating requests and write audit log entries."""
import json
import time
import uuid
from typing import Callable, Optional, Set

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.constants import AuditAction
from app.core.logging import get_logger

logger = get_logger(__name__)

_MUTATION_METHODS: Set[str] = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PATHS: Set[str] = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json"}

# Map HTTP method → audit action
_METHOD_TO_ACTION = {
    "POST": AuditAction.CREATE,
    "PUT": AuditAction.UPDATE,
    "PATCH": AuditAction.UPDATE,
    "DELETE": AuditAction.DELETE,
}

# Map URL path fragments → resource type names
_PATH_RESOURCE_MAP = {
    "/users": "user",
    "/organizations": "organization",
    "/workspaces": "workspace",
    "/projects": "project",
    "/documents": "document",
    "/requirements": "requirement",
    "/epics": "epic",
    "/user-stories": "user_story",
    "/sprints": "sprint",
    "/tasks": "task",
    "/approvals": "approval",
    "/ai-generations": "ai_generation",
    "/releases": "release",
    "/qa-test-cases": "qa_test_case",
}


def _infer_resource_type(path: str) -> str:
    """Infer the resource type from the request path."""
    for fragment, resource in _PATH_RESOURCE_MAP.items():
        if fragment in path:
            return resource
    return "unknown"


def _extract_resource_id(path: str) -> Optional[str]:
    """Extract a UUID-like segment from the URL path."""
    import re

    uuid_pattern = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
    )
    matches = uuid_pattern.findall(path)
    return matches[-1] if matches else None


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Asynchronously write audit records for all mutating API calls (POST/PUT/PATCH/DELETE).

    The actual DB write is deferred to a background task so that audit logging
    never blocks the main response.  Failures are logged but do not surface
    to the client.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only audit mutation methods
        if (
            request.method not in _MUTATION_METHODS
            or request.url.path in _SKIP_PATHS
        ):
            return await call_next(request)

        # Pre-read the request body to avoid BaseHTTPMiddleware body-streaming
        # deadlock when multiple BaseHTTPMiddleware instances are stacked.
        await request.body()

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000)

        # Only log successful mutations
        if response.status_code < 200 or response.status_code >= 400:
            return response

        try:
            path = request.url.path
            user_id: Optional[str] = getattr(request.state, "user_id", None)
            org_id: Optional[str] = getattr(request.state, "org_id", None)
            user_role: Optional[str] = getattr(request.state, "user_role", None)
            request_id: str = getattr(request.state, "request_id", str(uuid.uuid4()))

            action = _METHOD_TO_ACTION.get(request.method, AuditAction.UPDATE)
            resource_type = _infer_resource_type(path)
            resource_id = _extract_resource_id(path)

            # Write audit record in background to avoid blocking
            from fastapi import BackgroundTasks

            async def _write_audit() -> None:
                try:
                    from app.db.session import AsyncSessionLocal
                    from app.repositories.audit_log import AuditLogRepository
                    import uuid as _uuid

                    async with AsyncSessionLocal() as session:
                        repo = AuditLogRepository(session)
                        await repo.log(
                            action=action,
                            resource_type=resource_type,
                            resource_id=resource_id,
                            user_id=_uuid.UUID(user_id) if user_id else None,
                            user_role=user_role,
                            org_id=_uuid.UUID(org_id) if org_id else None,
                            ip_address=request.headers.get("X-Forwarded-For", request.client.host if request.client else None),
                            user_agent=request.headers.get("user-agent"),
                            request_id=request_id,
                            description=f"{request.method} {path} → {response.status_code} ({duration_ms}ms)",
                        )
                        await session.commit()
                except Exception as exc:
                    logger.warning("Audit log write failed", error=str(exc))

            import asyncio

            asyncio.ensure_future(_write_audit())

        except Exception as exc:
            logger.warning("Audit middleware error", error=str(exc))

        return response
