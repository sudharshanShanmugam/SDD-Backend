"""User schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.core.constants import UserRole
from app.schemas.common import BaseFilter, BaseSchema


class UserCreate(BaseSchema):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.VIEWER
    organization_id: Optional[UUID] = None
    timezone: str = "UTC"
    locale: str = "en"

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        from app.core.security import password_meets_requirements
        ok, errors = password_meets_requirements(v)
        if not ok:
            raise ValueError("; ".join(errors))
        return v

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class UserUpdate(BaseSchema):
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    avatar_url: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=30)
    timezone: Optional[str] = Field(None, max_length=50)
    locale: Optional[str] = Field(None, max_length=10)
    preferences: Optional[dict[str, Any]] = None


class UserRoleUpdate(BaseSchema):
    role: UserRole


class UserResponse(BaseSchema):
    id: UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    timezone: str
    locale: str
    organization_id: Optional[UUID] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserSummary(BaseSchema):
    """Compact user representation for embedding in other schemas."""
    id: UUID
    email: str
    full_name: str
    role: UserRole
    avatar_url: Optional[str] = None


class UserFilter(BaseFilter):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    organization_id: Optional[UUID] = None
