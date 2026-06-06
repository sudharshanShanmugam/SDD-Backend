"""Project schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field, field_validator

from app.core.constants import UserRole, WorkflowStage
from app.schemas.common import BaseFilter, BaseSchema


class ProjectCreate(BaseSchema):
    workspace_id: UUID
    name: str = Field(min_length=2, max_length=255)
    key: str = Field(min_length=2, max_length=10, pattern=r"^[A-Z0-9]+$")
    description: Optional[str] = Field(None, max_length=2000)
    settings: Optional[dict[str, Any]] = None
    ai_config: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None

    @field_validator("key")
    @classmethod
    def uppercase_key(cls, v: str) -> str:
        return v.upper().strip()


class ProjectUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    workflow_stage: Optional[WorkflowStage] = None
    settings: Optional[dict[str, Any]] = None
    ai_config: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None
    start_date: Optional[str] = None
    target_date: Optional[str] = None


class ProjectResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    name: str
    key: str
    description: Optional[str] = None
    workflow_stage: WorkflowStage
    is_active: bool
    is_archived: bool
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    owner_id: Optional[UUID] = None
    tags: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime


class ProjectSummary(BaseSchema):
    id: UUID
    name: str
    key: str
    workflow_stage: WorkflowStage
    is_active: bool


class ProjectMemberResponse(BaseSchema):
    id: UUID
    project_id: UUID
    user_id: UUID
    role: UserRole
    is_active: bool
    created_at: datetime


class ProjectFilter(BaseFilter):
    organization_id: Optional[UUID] = None
    workspace_id: Optional[UUID] = None
    workflow_stage: Optional[WorkflowStage] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
