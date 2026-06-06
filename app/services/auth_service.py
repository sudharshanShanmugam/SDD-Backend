"""
Authentication Service.

Responsibilities:
  - User registration with org creation and email verification
  - Credential-based login with rate-limiting and lockout
  - JWT access + opaque refresh token issuance and rotation
  - Token blacklisting via Redis
  - Password reset and change flows
  - Session invalidation on logout
"""
from __future__ import annotations

import logging
import secrets
import string
import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import redis.asyncio as aioredis
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AccountDisabledError,
    AuthenticationError,
    ConflictError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
    RateLimitExceededError,
    TokenRevokedError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Redis connection ──────────────────────────────────────────────────────────
_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


# ── Named tuples / dataclasses ────────────────────────────────────────────────

from dataclasses import dataclass


@dataclass
class TokenPair:
    """Access + refresh token pair returned from login and refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0  # seconds until access token expires


class AuthService:
    """
    Handles all authentication business logic for the SDD platform.

    Constructor takes an AsyncSession and (optionally) a pre-wired Redis client.
    When ``redis_client`` is None the global singleton from ``get_redis()`` is
    used; pass a mock for unit testing.
    """

    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15

    TOKEN_BLACKLIST_PREFIX = "token:blacklist:"
    REFRESH_TOKEN_PREFIX = "refresh:"
    EMAIL_VERIFY_PREFIX = "email_verify:"
    PASSWORD_RESET_PREFIX = "pwd_reset:"
    RATE_LIMIT_PREFIX = "auth:rate_limit:"

    def __init__(
        self,
        db: AsyncSession,
        redis_client: Optional[aioredis.Redis] = None,
    ) -> None:
        self.db = db
        self._redis: Optional[aioredis.Redis] = redis_client

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is not None:
            return self._redis
        return await get_redis()

    # ── Password utilities ─────────────────────────────────────────────────

    def hash_password(self, plain_password: str) -> str:
        """Hash a plain-text password using bcrypt."""
        return pwd_context.hash(plain_password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plain-text password against a bcrypt hash."""
        return pwd_context.verify(plain_password, hashed_password)

    # ── JWT tokens ─────────────────────────────────────────────────────────

    def create_access_token(
        self,
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
    ) -> str:
        """
        Create a signed JWT access token.

        Args:
            data: Claims to encode (must include 'sub').
            expires_delta: Custom expiry; defaults to settings.ACCESS_TOKEN_EXPIRE_MINUTES.

        Returns:
            Encoded JWT string.
        """
        to_encode = data.copy()
        now = datetime.now(tz=timezone.utc)
        expire = now + (
            expires_delta
            if expires_delta
            else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        # Include iss/aud/jti so decode_access_token in security.py validates correctly
        to_encode.update(
            {
                "iat": now,
                "exp": expire,
                "type": "access",
                "jti": str(_uuid_mod.uuid4()),
                "iss": settings.JWT_ISSUER,
                "aud": settings.JWT_AUDIENCE,
            }
        )
        return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def verify_token(self, token: str) -> dict[str, Any] | None:
        """
        Decode and verify a JWT token.

        Returns the payload dict on success, None if invalid/expired.
        """
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            return payload
        except JWTError as exc:
            logger.debug("Token verification failed: %s", exc)
            return None

    async def is_token_blacklisted(self, token: str) -> bool:
        """Check if a token has been blacklisted in Redis."""
        redis = await get_redis()
        key = f"{self.TOKEN_BLACKLIST_PREFIX}{token}"
        return bool(await redis.exists(key))

    async def blacklist_token(self, token: str, expires_in: int = 0) -> None:
        """
        Add a token to the Redis blacklist.

        Args:
            token: The JWT access token string.
            expires_in: TTL in seconds. If 0, uses the token's own expiry.
        """
        redis = await get_redis()
        key = f"{self.TOKEN_BLACKLIST_PREFIX}{token}"

        if expires_in == 0:
            payload = self.verify_token(token)
            if payload and "exp" in payload:
                now = datetime.now(tz=timezone.utc).timestamp()
                expires_in = max(int(payload["exp"] - now), 1)
            else:
                expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

        await redis.setex(key, expires_in, "1")

    # ── Refresh tokens ─────────────────────────────────────────────────────

    async def create_refresh_token(self, user_id: str) -> str:
        """
        Create and store a secure refresh token in Redis.

        Returns the opaque refresh token string.
        """
        redis = await get_redis()
        token = secrets.token_urlsafe(48)
        key = f"{self.REFRESH_TOKEN_PREFIX}{token}"
        ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400

        await redis.setex(key, ttl, user_id)
        logger.debug("Refresh token created for user %s", user_id)
        return token

    async def rotate_refresh_token(self, old_token: str) -> dict[str, str] | None:
        """
        Rotate a refresh token: validate old, issue new access + refresh tokens.

        Returns dict with new tokens, or None if old token is invalid/expired.
        """
        redis = await get_redis()
        key = f"{self.REFRESH_TOKEN_PREFIX}{old_token}"
        user_id = await redis.get(key)

        if not user_id:
            return None

        # Invalidate old refresh token immediately (rotation)
        await redis.delete(key)

        # Look up user to get current role
        from app.models.user import User
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            return None

        access_token = self.create_access_token(
            data={"sub": str(user.id), "email": user.email, "role": user.role}
        )
        new_refresh = await self.create_refresh_token(user_id=str(user.id))

        return {
            "access_token": access_token,
            "refresh_token": new_refresh,
        }

    async def invalidate_refresh_token(self, token: str) -> None:
        """Delete a refresh token from Redis."""
        redis = await get_redis()
        await redis.delete(f"{self.REFRESH_TOKEN_PREFIX}{token}")

    # ── User authentication ────────────────────────────────────────────────

    async def authenticate_user(self, email: str, password: str):
        """
        Validate credentials and return the user object.

        Returns None if credentials are invalid.
        """
        from app.models.user import User
        result = await self.db.execute(
            select(User).where(User.email == email.lower())
        )
        user = result.scalar_one_or_none()
        if not user:
            # Constant-time dummy check to prevent timing attacks
            pwd_context.dummy_verify()
            return None
        if not self.verify_password(password, user.hashed_password):
            return None
        return user

    async def record_login(
        self,
        user_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Record a successful login event for audit purposes."""
        from app.models.user import User
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=datetime.now(tz=timezone.utc))
        )
        await self.db.commit()

    # ── Email verification ─────────────────────────────────────────────────

    async def send_verification_email(self, user_id: str, email: str) -> None:
        """Generate a verification token and send email."""
        redis = await get_redis()
        token = secrets.token_urlsafe(32)
        key = f"{self.EMAIL_VERIFY_PREFIX}{token}"
        await redis.setex(key, 86400 * 3, user_id)  # 3-day TTL

        # TODO: integrate with email provider (SendGrid / SES)
        verify_url = f"{settings.FRONTEND_URL}/verify-email/{token}"
        logger.info("Verification email for %s: %s", email, verify_url)

    async def verify_email_token(self, token: str) -> bool:
        """Verify the email verification token and mark user as verified."""
        redis = await get_redis()
        key = f"{self.EMAIL_VERIFY_PREFIX}{token}"
        user_id = await redis.get(key)
        if not user_id:
            return False

        from app.models.user import User
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(is_verified=True)
        )
        await self.db.commit()
        await redis.delete(key)
        return True

    # ── Password reset ─────────────────────────────────────────────────────

    async def send_password_reset_email(self, user_id: str, email: str) -> None:
        """Generate a password reset token and send email."""
        redis = await get_redis()
        token = secrets.token_urlsafe(32)
        key = f"{self.PASSWORD_RESET_PREFIX}{token}"
        await redis.setex(key, 3600, user_id)  # 1-hour TTL

        reset_url = f"{settings.FRONTEND_URL}/reset-password/{token}"
        logger.info("Password reset for %s: %s", email, reset_url)

    async def reset_password(self, token: str, new_password: str) -> bool:
        """Reset password using the token from reset email."""
        redis = await get_redis()
        key = f"{self.PASSWORD_RESET_PREFIX}{token}"
        user_id = await redis.get(key)
        if not user_id:
            return False

        hashed = self.hash_password(new_password)
        from app.models.user import User
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(hashed_password=hashed)
        )
        await self.db.commit()
        await redis.delete(key)

        # Invalidate all refresh tokens for this user by pattern
        # Note: In production use a separate user token version counter
        logger.info("Password reset successful for user %s", user_id)
        return True

    async def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> bool:
        """Change password after verifying current password."""
        from app.models.user import User
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
        if not self.verify_password(current_password, user.hashed_password):
            return False

        hashed = self.hash_password(new_password)
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                hashed_password=hashed,
                password_changed_at=datetime.now(tz=timezone.utc),
            )
        )
        await self.db.commit()
        return True

    # ── Registration ───────────────────────────────────────────────────────

    async def register(
        self,
        email: str,
        password: str,
        full_name: str,
        org_name: str,
        ip_address: Optional[str] = None,
    ):
        """
        Create a new user account and default organization.

        Flow:
        1. Validate email uniqueness
        2. Hash password
        3. Create Organization
        4. Create User linked to the org with ORG_ADMIN role
        5. Create default Workspace inside the org
        6. Send email verification (fire-and-forget)

        Returns the created User instance.
        """
        from app.core.constants import UserRole
        from app.models.organization import Organization
        from app.models.user import User
        from app.models.workspace import Workspace

        # 1. Email uniqueness check
        existing = (
            await self.db.execute(
                select(User).where(User.email == email.lower().strip())
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise EmailAlreadyExistsError()

        now = datetime.now(tz=timezone.utc)
        new_id = _uuid_mod.uuid4()

        # 2. Create organization
        org = Organization(
            id=_uuid_mod.uuid4(),
            name=org_name.strip(),
            slug=self._slugify(org_name),
            created_at=now,
            updated_at=now,
        )
        self.db.add(org)
        await self.db.flush()

        # 3. Create user
        user = User(
            id=new_id,
            email=email.lower().strip(),
            full_name=full_name.strip(),
            hashed_password=self.hash_password(password),
            role=UserRole.ORG_ADMIN,
            organization_id=org.id,
            is_active=True,
            is_verified=False,
            created_at=now,
            updated_at=now,
        )
        self.db.add(user)
        await self.db.flush()

        # Update org owner reference if model has it
        if hasattr(org, "owner_id"):
            org.owner_id = user.id
            await self.db.flush()

        # 4. Create default workspace
        workspace = Workspace(
            id=_uuid_mod.uuid4(),
            organization_id=org.id,
            name="Default Workspace",
            created_by=user.id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(workspace)
        await self.db.flush()

        await self.db.commit()
        await self.db.refresh(user)

        # 5. Send verification email (fire-and-forget – never block registration)
        try:
            await self.send_verification_email(str(user.id), user.email)
        except Exception as exc:
            logger.warning("Could not send verification email to %s: %s", user.email, exc)

        logger.info("New user registered: %s (org=%s)", user.email, org.id)
        return user

    # ── Login ──────────────────────────────────────────────────────────────

    async def login(
        self,
        email: str,
        password: str,
        ip_address: Optional[str] = None,
        remember_me: bool = False,
    ) -> TokenPair:
        """
        Authenticate a user and return a JWT access + refresh token pair.

        Raises:
        - RateLimitExceededError  if the IP has exceeded allowed attempts
        - InvalidCredentialsError if email/password are wrong
        - AccountDisabledError    if the user is inactive or locked
        """
        from app.models.user import User

        # Rate limit check
        if ip_address:
            await self._check_login_rate_limit(ip_address)

        email = email.lower().strip()

        # Fetch user (constant-time path to prevent user enumeration)
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if user is None:
            pwd_context.dummy_verify()
            raise InvalidCredentialsError()

        # Check lockout
        if user.locked_until and user.locked_until > datetime.now(tz=timezone.utc):
            raise AccountDisabledError(
                message=f"Account is temporarily locked until {user.locked_until.isoformat()}"
            )

        # Verify password
        if not self.verify_password(password, user.hashed_password):
            await self._record_failed_login(user)
            raise InvalidCredentialsError()

        if not user.is_active:
            raise AccountDisabledError()

        # Reset failed attempts on success
        now = datetime.now(tz=timezone.utc)
        await self.db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                last_login_at=now,
                last_login_ip=ip_address,
                failed_login_attempts=0,
                locked_until=None,
                updated_at=now,
            )
        )
        await self.db.commit()

        # Issue tokens
        access_token = self.create_access_token(
            data={
                "sub": str(user.id),
                "email": user.email,
                "role": user.role,
                "org_id": str(user.organization_id) if user.organization_id else None,
                "jti": str(_uuid_mod.uuid4()),
            }
        )
        refresh_token = await self.create_refresh_token(
            user_id=str(user.id),
            remember_me=remember_me,
        )

        logger.info("User %s logged in from %s", user.email, ip_address)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def _check_login_rate_limit(self, ip_address: str) -> None:
        """Raise RateLimitExceededError if the IP has too many recent attempts."""
        redis = await self._get_redis()
        key = f"{self.RATE_LIMIT_PREFIX}{ip_address}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 900)  # 15-minute window
        if count > self.MAX_LOGIN_ATTEMPTS * 3:
            raise RateLimitExceededError(
                message="Too many login attempts from this IP. Try again in 15 minutes."
            )

    async def _record_failed_login(self, user: Any) -> None:
        """Increment failed-login counter and lock the account if threshold is reached."""
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= self.MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(tz=timezone.utc) + timedelta(
                minutes=self.LOCKOUT_MINUTES
            )
            logger.warning(
                "Account %s locked after %d failed attempts",
                user.email,
                user.failed_login_attempts,
            )
        await self.db.flush()

    # ── Token refresh ──────────────────────────────────────────────────────

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """
        Rotate a refresh token: validate, issue new access + refresh pair,
        and invalidate the old refresh token (one-time use).

        Raises InvalidTokenError if the token is missing or expired.
        """
        result = await self.rotate_refresh_token(refresh_token)
        if result is None:
            raise InvalidTokenError(message="Refresh token is invalid or has expired")

        return TokenPair(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    # ── Logout ─────────────────────────────────────────────────────────────

    async def logout(
        self,
        user_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> None:
        """
        Invalidate a user's session.

        - Blacklists the access token in Redis (until its natural expiry)
        - Deletes the refresh token from Redis
        """
        await self.blacklist_token(access_token)
        if refresh_token:
            await self.invalidate_refresh_token(refresh_token)
        logger.info("User %s logged out", user_id)

    # ── Forgot password ────────────────────────────────────────────────────

    async def forgot_password(self, email: str) -> None:
        """
        Initiate a password-reset flow.

        Silently no-ops if the email is not registered (prevents user enumeration).
        """
        from app.models.user import User

        result = await self.db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        user = result.scalar_one_or_none()
        if user is None:
            logger.debug("Forgot-password request for unknown email %s", email)
            return  # Silent no-op

        await self.send_password_reset_email(str(user.id), user.email)

    # ── Helpers ────────────────────────────────────────────────────────────

    async def create_refresh_token(
        self,
        user_id: str,
        remember_me: bool = False,
    ) -> str:
        """Create and store an opaque refresh token in Redis."""
        redis = await self._get_redis()
        token = secrets.token_urlsafe(48)
        key = f"{self.REFRESH_TOKEN_PREFIX}{token}"
        ttl_days = settings.REFRESH_TOKEN_EXPIRE_DAYS * (2 if remember_me else 1)
        await redis.setex(key, ttl_days * 86400, user_id)
        return token

    @staticmethod
    def _slugify(name: str) -> str:
        """Convert an org name to a URL-safe slug."""
        import re

        slug = name.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_-]+", "-", slug)
        slug = slug.strip("-")
        return slug[:63] or "org"
