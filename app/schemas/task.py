"""Task schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.core.constants import RequirementPriority, TaskStatus, TaskType
from app.schemas.common import BaseFilter, BaseSchema


class TaskCreate(BaseSchema):
    user_story_id: Optional[UUID] = None
    sprint_id: Optional[UUID] = None
    title: str = Field(min_length=3, max_length=500)
    description: Optional[str] = None
    task_type: TaskType = TaskType.FEATURE
    priority: RequirementPriority = RequirementPriority.MEDIUM
    story_points: Optional[int] = Field(None, ge=0, le=999)
    time_estimate_hours: Optional[float] = Field(None, ge=0)
    assignee_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    tags: Optional[list[str]] = None
    tech_notes: Optional[str] = None


class TaskUpdate(BaseSchema):
    title: Optional[str] = Field(None, min_length=3, max_length=500)
    description: Optional[str] = None
    task_type: Optional[TaskType] = None
    status: Optional[TaskStatus] = None
    priority: Optional[RequirementPriority] = None
    story_points: Optional[int] = Field(None, ge=0, le=999)
    time_estimate_hours: Optional[float] = Field(None, ge=0)
    time_actual_hours: Optional[float] = Field(None, ge=0)
    time_remaining_hours: Optional[float] = Field(None, ge=0)
    assignee_id: Optional[UUID] = None
    sprint_id: Optional[UUID] = None
    blocked_reason: Optional[str] = None
    tech_notes: Optional[str] = None
    pr_links: Optional[list[str]] = None
    tags: Optional[list[str]] = None


class TaskResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    project_id: UUID
    user_story_id: Optional[UUID] = None
    sprint_id: Optional[UUID] = None
    assignee_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    task_number: str
    title: str
    description: Optional[str] = None
    task_type: TaskType
    status: TaskStatus
    priority: RequirementPriority
    story_points: Optional[int] = None
    time_estimate_hours: Optional[float] = None
    time_actual_hours: Optional[float] = None
    time_remaining_hours: Optional[float] = None
    order_index: int
    blocked_reason: Optional[str] = None
    is_ai_generated: bool
    tech_notes: Optional[str] = None
    pr_links: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime


class TaskFilter(BaseFilter):
    project_id: Optional[UUID] = None
    user_story_id: Optional[UUID] = None
    sprint_id: Optional[UUID] = None
    assignee_id: Optional[UUID] = None
    task_type: Optional[TaskType] = None
    status: Optional[TaskStatus] = None
    priority: Optional[RequirementPriority] = None
    is_ai_generated: Optional[bool] = None
