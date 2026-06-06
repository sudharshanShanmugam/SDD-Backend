"""Organization schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.core.constants import OrgPlan, UserRole
from app.schemas.common import BaseFilter, BaseSchema


class OrganizationCreate(BaseSchema):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = Field(None, max_length=1000)
    plan: OrgPlan = OrgPlan.FREE
    billing_email: Optional[EmailStr] = None

    @field_validator("slug")
    @classmethod
    def lowercase_slug(cls, v: str) -> str:
        return v.lower().strip()


class OrganizationUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    logo_url: Optional[str] = Field(None, max_length=500)
    website: Optional[str] = Field(None, max_length=255)
    billing_email: Optional[EmailStr] = None
    billing_address: Optional[dict[str, Any]] = None
    settings: Optional[dict[str, Any]] = None
    ai_settings: Optional[dict[str, Any]] = None
    feature_flags: Optional[dict[str, Any]] = None


class OrganizationResponse(BaseSchema):
    id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    plan: OrgPlan
    is_active: bool
    max_members: int
    max_projects: int
    max_storage_gb: int
    billing_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class OrganizationSummary(BaseSchema):
    id: UUID
    name: str
    slug: str
    plan: OrgPlan
    logo_url: Optional[str] = None


class AddMemberRequest(BaseSchema):
    user_id: Optional[UUID] = None
    email: Optional[EmailStr] = None
    role: UserRole = UserRole.VIEWER

    @field_validator("user_id", "email", mode="after")
    @classmethod
    def require_one(cls, v: Any, info: Any) -> Any:
        return v


class MemberResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: UserRole
    is_active: bool
    created_at: datetime


class OrganizationFilter(BaseFilter):
    plan: Optional[OrgPlan] = None
    is_active: Optional[bool] = None
