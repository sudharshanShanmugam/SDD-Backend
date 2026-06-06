"""Security utilities: JWT, bcrypt, token management."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.constants import TOKEN_TYPE_ACCESS, TOKEN_TYPE_REFRESH, TOKEN_TYPE_RESET_PASSWORD, TOKEN_TYPE_EMAIL_VERIFY

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# ── Password utilities ────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def password_meets_requirements(password: str) -> tuple[bool, list[str]]:
    """Validate password complexity requirements."""
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")
    if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        errors.append("Password must contain at least one special character")
    return len(errors) == 0, errors


# ── Token creation ────────────────────────────────────────────────────────────

def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    additional_claims: Optional[dict[str, Any]] = None,
) -> str:
    """Create a signed JWT token."""
    now = datetime.now(tz=timezone.utc)
    expire = now + expires_delta
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    if additional_claims:
        payload.update(additional_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    user_id: str,
    org_id: Optional[str] = None,
    role: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """Create a short-lived access token."""
    claims: dict[str, Any] = {}
    if org_id:
        claims["org_id"] = org_id
    if role:
        claims["role"] = role
    if extra:
        claims.update(extra)
    return _create_token(
        subject=user_id,
        token_type=TOKEN_TYPE_ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        additional_claims=claims,
    )


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token."""
    return _create_token(
        subject=user_id,
        token_type=TOKEN_TYPE_REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def create_password_reset_token(user_id: str) -> str:
    """Create a short-lived password-reset token."""
    return _create_token(
        subject=user_id,
        token_type=TOKEN_TYPE_RESET_PASSWORD,
        expires_delta=timedelta(hours=1),
    )


def create_email_verification_token(user_id: str) -> str:
    """Create an email-verification token."""
    return _create_token(
        subject=user_id,
        token_type=TOKEN_TYPE_EMAIL_VERIFY,
        expires_delta=timedelta(days=3),
    )


# ── Token verification ────────────────────────────────────────────────────────

class TokenData:
    """Decoded token payload container."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.subject: str = payload["sub"]
        self.token_type: str = payload.get("type", TOKEN_TYPE_ACCESS)
        self.jti: str = payload.get("jti", "")
        self.org_id: Optional[str] = payload.get("org_id")
        self.role: Optional[str] = payload.get("role")
        self.issued_at: Optional[datetime] = (
            datetime.fromtimestamp(payload["iat"], tz=timezone.utc) if "iat" in payload else None
        )
        self.expires_at: Optional[datetime] = (
            datetime.fromtimestamp(payload["exp"], tz=timezone.utc) if "exp" in payload else None
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return True
        return datetime.now(tz=timezone.utc) > self.expires_at


def decode_token(token: str, expected_type: Optional[str] = None) -> TokenData:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
    )
    token_data = TokenData(payload)
    if expected_type and token_data.token_type != expected_type:
        raise JWTError(f"Expected token type '{expected_type}', got '{token_data.token_type}'")
    return token_data


def decode_access_token(token: str) -> TokenData:
    return decode_token(token, expected_type=TOKEN_TYPE_ACCESS)


def decode_refresh_token(token: str) -> TokenData:
    return decode_token(token, expected_type=TOKEN_TYPE_REFRESH)


# ── Utility ───────────────────────────────────────────────────────────────────

def generate_secure_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(nbytes)


def generate_api_key() -> str:
    """Generate an API key with a recognisable prefix."""
    return f"sdd_{secrets.token_urlsafe(40)}"
