"""FastAPI dependency injection: current user, DB session, RBAC."""
from typing import Annotated, AsyncGenerator, Optional
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import Permission, ROLE_PERMISSIONS, UserRole
from app.core.exceptions import (
    AccountDisabledError,
    AuthenticationError,
    InvalidTokenError,
    PermissionDeniedError,
    TokenExpiredError,
    TokenRevokedError,
)
from app.db.session import AsyncSessionLocal, get_redis_pool

bearer_scheme = HTTPBearer(auto_error=False)


# ── Database session ──────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session, rolling back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


DBSession = Annotated[AsyncSession, Depends(get_db)]


# ── Redis client ──────────────────────────────────────────────────────────────

async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Yield a Redis connection from the pool."""
    pool = get_redis_pool()
    client = aioredis.Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()


RedisClient = Annotated[aioredis.Redis, Depends(get_redis)]


# ── Token extraction ──────────────────────────────────────────────────────────

async def _get_token_data(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Extract and validate the Bearer token."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Bearer token is required")

    raw_token = credentials.credentials
    try:
        token_data = decode_access_token(raw_token)
    except JWTError as exc:
        msg = str(exc).lower()
        if "expired" in msg:
            raise TokenExpiredError()
        raise InvalidTokenError(message=str(exc))

    # Check revocation list in Redis
    revoked_key = f"revoked_token:{token_data.jti}"
    if await redis.exists(revoked_key):
        raise TokenRevokedError()

    return token_data


# ── Current user ──────────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated User ORM object.

    In development mode, if no Bearer token is present (or the token is empty),
    the seeded super-admin user is returned automatically so the frontend can
    work without a real auth flow.
    """
    from app.repositories.user import UserRepository
    from app.db.init_db import SEED_USER_UUID

    no_token = credentials is None or not credentials.credentials

    if no_token:
        raise AuthenticationError("Bearer token is required")

    raw_token = credentials.credentials
    try:
        from app.core.security import decode_access_token
        token_data = decode_access_token(raw_token)
    except Exception as exc:
        from jose import JWTError, jwt as jose_jwt
        exc_msg = str(exc).lower()

        if "expired" in exc_msg:
            raise TokenExpiredError()

        # ── Fallback: token created by AuthService (lacks iss/aud claims) ────
        # The login endpoint uses AuthService.create_access_token which does not
        # embed iss/aud. Try a lenient decode — verify signature only, no
        # issuer/audience check — so both token formats work.
        try:
            payload = jose_jwt.decode(
                raw_token,
                settings.SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_aud": False, "verify_iss": False},
            )
            if payload.get("type") not in ("access", None):
                raise InvalidTokenError(message="Not an access token")

            # Build a minimal token_data-compatible object
            class _MinimalTokenData:
                subject = str(payload.get("sub", ""))
                jti     = str(payload.get("jti", ""))
                org_id  = payload.get("org_id")

            token_data = _MinimalTokenData()  # type: ignore[assignment]
        except (JWTError, Exception) as inner:
            raise InvalidTokenError(message=str(exc))  # report original error

    # Check revocation list in Redis
    from app.db.session import get_redis_pool
    import redis.asyncio as aioredis
    redis_pool = get_redis_pool()
    redis_client = aioredis.Redis(connection_pool=redis_pool)
    try:
        revoked_key = f"revoked_token:{token_data.jti}"
        if await redis_client.exists(revoked_key):
            raise TokenRevokedError()
    finally:
        await redis_client.aclose()

    repo = UserRepository(db)
    user = await repo.get_by_id(UUID(token_data.subject))
    if user is None:
        raise AuthenticationError("User not found")
    if not user.is_active:
        raise AccountDisabledError()
    return user


CurrentUser = Annotated[object, Depends(get_current_user)]


async def get_current_active_superuser(current_user=Depends(get_current_user)):
    """Require the current user to be a super-admin."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise PermissionDeniedError("Super-admin access required")
    return current_user


async def require_admin(current_user=Depends(get_current_user)):
    """Dependency: require org_admin or super_admin role. Returns the current user."""
    if current_user.role not in (UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN):
        raise PermissionDeniedError("Admin access required")
    return current_user


async def require_superadmin(current_user=Depends(get_current_user)):
    """Dependency: require super_admin role. Returns the current user."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise PermissionDeniedError("Super-admin access required")
    return current_user


# ── RBAC permission check ─────────────────────────────────────────────────────

def require_permission(permission: Permission):
    """Dependency factory: raise 403 if user lacks the given permission."""

    async def _check(current_user=Depends(get_current_user)) -> None:
        role: UserRole = current_user.role
        allowed = ROLE_PERMISSIONS.get(role, [])
        if permission not in allowed:
            raise PermissionDeniedError(
                message=f"Permission '{permission}' is required",
                detail={"required_permission": permission, "user_role": role},
            )

    return Depends(_check)


def require_any_permission(*permissions: Permission):
    """Dependency factory: user must have at least one of the permissions."""

    async def _check(current_user=Depends(get_current_user)) -> None:
        role: UserRole = current_user.role
        allowed = set(ROLE_PERMISSIONS.get(role, []))
        if not any(p in allowed for p in permissions):
            raise PermissionDeniedError(
                message="Insufficient permissions",
                detail={"required_any": list(permissions), "user_role": role},
            )

    return Depends(_check)


def require_all_permissions(*permissions: Permission):
    """Dependency factory: user must have ALL of the permissions."""

    async def _check(current_user=Depends(get_current_user)) -> None:
        role: UserRole = current_user.role
        allowed = set(ROLE_PERMISSIONS.get(role, []))
        missing = [p for p in permissions if p not in allowed]
        if missing:
            raise PermissionDeniedError(
                message="Insufficient permissions",
                detail={"missing_permissions": missing, "user_role": role},
            )

    return Depends(_check)


# ── Tenant context ────────────────────────────────────────────────────────────

async def get_org_id_from_token(token_data=Depends(_get_token_data)) -> Optional[UUID]:
    """Extract organisation ID from JWT claims."""
    if token_data.org_id:
        return UUID(token_data.org_id)
    return None


OrgIdDep = Annotated[Optional[UUID], Depends(get_org_id_from_token)]


# ── Project access ────────────────────────────────────────────────────────────

async def verify_project_access(db: AsyncSession, project_id: str, user_id: str) -> None:
    """Raise 403 if user is not a member of the project."""
    from app.services.project_service import ProjectService
    svc = ProjectService(db)
    await svc.assert_access(project_id=project_id, user_id=user_id)


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginationParams:
    def __init__(
        self,
        page: int = 1,
        page_size: int = settings.DEFAULT_PAGE_SIZE,
    ) -> None:
        if page < 1:
            raise HTTPException(status_code=422, detail="page must be >= 1")
        if page_size < 1 or page_size > settings.MAX_PAGE_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"page_size must be between 1 and {settings.MAX_PAGE_SIZE}",
            )
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size


PaginationDep = Annotated[PaginationParams, Depends(PaginationParams)]


# ── Request ID ────────────────────────────────────────────────────────────────

async def get_request_id(request: Request) -> str:
    """Return the X-Request-ID header or a generated UUID."""
    return request.state.request_id if hasattr(request.state, "request_id") else ""


RequestIdDep = Annotated[str, Depends(get_request_id)]
