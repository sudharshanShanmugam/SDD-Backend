"""Authentication and identity schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import EmailStr, Field, field_validator, model_validator

from app.core.constants import UserRole
from app.schemas.common import BaseSchema


# ── Request schemas ───────────────────────────────────────────────────────────


class LoginRequest(BaseSchema):
    """Credentials submitted on the /auth/login endpoint."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=1, description="Plain-text password")
    remember_me: bool = Field(
        default=False,
        description="When true, extend the refresh-token TTL",
    )


class RegisterRequest(BaseSchema):
    """Payload for new account creation."""

    email: EmailStr = Field(..., description="Email address for the new account")
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=255)
    org_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Name of the organization to create",
    )

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        from app.core.security import password_meets_requirements

        ok, errors = password_meets_requirements(v)
        if not ok:
            raise ValueError("; ".join(errors))
        return v

    @field_validator("full_name", "org_name", mode="before")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        return v.strip() if v else v


class RefreshRequest(BaseSchema):
    """Body for the /auth/refresh endpoint."""

    refresh_token: str = Field(..., description="Opaque refresh token string")


class ForgotPasswordRequest(BaseSchema):
    """Request a password-reset email."""

    email: EmailStr


class ResetPasswordRequest(BaseSchema):
    """Complete a password reset using the emailed token."""

    token: str = Field(..., description="Password-reset token from the email link")
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        from app.core.security import password_meets_requirements

        ok, errors = password_meets_requirements(v)
        if not ok:
            raise ValueError("; ".join(errors))
        return v

    @model_validator(mode="after")
    def passwords_match(self) -> "ResetPasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password must match")
        return self


class ChangePasswordRequest(BaseSchema):
    """Authenticated user changing their own password."""

    current_password: str = Field(..., description="Current plain-text password")
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        from app.core.security import password_meets_requirements

        ok, errors = password_meets_requirements(v)
        if not ok:
            raise ValueError("; ".join(errors))
        return v

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password must match")
        return self


class EmailVerifyRequest(BaseSchema):
    """Token submitted on the email-verification link."""

    token: str


# ── Token / user-in-token schemas ─────────────────────────────────────────────


class ProjectPermission(BaseSchema):
    """Per-project role embedded in the access token."""

    project_id: UUID
    role: UserRole


class UserInToken(BaseSchema):
    """
    Minimal user representation embedded in JWT tokens.

    Keep this small – it is serialised into every access token.
    """

    id: UUID
    email: EmailStr
    full_name: str
    role: UserRole
    organization_id: Optional[UUID] = None
    is_active: bool = True
    is_verified: bool = False
    project_permissions: List[ProjectPermission] = Field(default_factory=list)


class TokenResponse(BaseSchema):
    """Pair of tokens returned on successful login or refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access-token TTL in seconds")
    user: Optional[UserInToken] = Field(
        default=None,
        description="Embedded user info; avoids a separate /me round-trip",
    )


# ── Internal / raw JWT payload ────────────────────────────────────────────────


class TokenPayload(BaseSchema):
    """Raw decoded JWT payload – used internally by auth middleware."""

    sub: str
    type: str
    org_id: Optional[str] = None
    role: Optional[str] = None
    jti: str
    iat: Optional[int] = None
    exp: Optional[int] = None
