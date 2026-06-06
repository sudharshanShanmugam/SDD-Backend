"""Workspace schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field, field_validator

from app.core.constants import UserRole
from app.schemas.common import BaseFilter, BaseSchema


class WorkspaceCreate(BaseSchema):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = Field(None, max_length=1000)
    icon: Optional[str] = Field(None, max_length=50)
    color: Optional[str] = Field(None, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$")
    settings: Optional[dict[str, Any]] = None

    @field_validator("slug")
    @classmethod
    def lowercase_slug(cls, v: str) -> str:
        return v.lower().strip()


class WorkspaceUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    icon: Optional[str] = Field(None, max_length=50)
    color: Optional[str] = Field(None, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$")
    settings: Optional[dict[str, Any]] = None


class WorkspaceResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime


class WorkspaceSummary(BaseSchema):
    id: UUID
    name: str
    slug: str
    icon: Optional[str] = None
    color: Optional[str] = None


class WorkspaceMemberResponse(BaseSchema):
    id: UUID
    workspace_id: UUID
    user_id: UUID
    role: UserRole
    is_active: bool
    created_at: datetime


class WorkspaceFilter(BaseFilter):
    organization_id: Optional[UUID] = None
    is_active: Optional[bool] = None
