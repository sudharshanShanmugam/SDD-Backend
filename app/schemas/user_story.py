"""User Story schemas – create, update, response, detail, sprint assignment."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field, field_validator

from app.core.constants import ApprovalStatus, RequirementPriority, StoryStatus
from app.schemas.common import BaseFilter, BaseSchema


# ── Request schemas ────────────────────────────────────────────────────────────


class UserStoryCreate(BaseSchema):
    """Payload for creating a new user story."""

    epic_id: Optional[UUID] = Field(
        default=None, description="Epic this story belongs to"
    )
    requirement_id: Optional[UUID] = Field(
        default=None, description="Source requirement driving this story"
    )
    title: str = Field(..., min_length=3, max_length=500)
    # INVEST narrative format
    as_a: Optional[str] = Field(
        default=None,
        max_length=255,
        description="User role – 'As a [role]'",
    )
    i_want: Optional[str] = Field(
        default=None, description="Goal – 'I want [goal]'"
    )
    so_that: Optional[str] = Field(
        default=None, description="Benefit – 'So that [benefit]'"
    )
    description: Optional[str] = Field(default=None, max_length=10_000)
    acceptance_criteria: Optional[str] = Field(default=None, max_length=10_000)
    definition_of_done: Optional[str] = Field(default=None, max_length=5_000)
    priority: RequirementPriority = Field(default=RequirementPriority.MEDIUM)
    story_points: Optional[int] = Field(None, ge=0, le=999)
    business_value: Optional[int] = Field(
        None, ge=0, le=100, description="Business value score 0-100"
    )
    type: Optional[str] = Field(
        default=None,
        description="Story type: feature, bug, chore, spike",
    )
    labels: Optional[List[str]] = Field(default=None, max_length=20)
    tags: Optional[List[str]] = Field(default=None, max_length=20)

    @field_validator("labels", "tags", mode="before")
    @classmethod
    def clean_list(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        return [item.strip() for item in v if item and item.strip()]


class UserStoryUpdate(BaseSchema):
    """Partial-update payload for an existing user story."""

    title: Optional[str] = Field(None, min_length=3, max_length=500)
    as_a: Optional[str] = Field(None, max_length=255)
    i_want: Optional[str] = None
    so_that: Optional[str] = None
    description: Optional[str] = Field(None, max_length=10_000)
    acceptance_criteria: Optional[str] = Field(None, max_length=10_000)
    definition_of_done: Optional[str] = Field(None, max_length=5_000)
    status: Optional[StoryStatus] = None
    priority: Optional[RequirementPriority] = None
    story_points: Optional[int] = Field(None, ge=0, le=999)
    business_value: Optional[int] = Field(None, ge=0, le=100)
    epic_id: Optional[UUID] = None
    labels: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    # INVEST flags
    is_independent: Optional[bool] = None
    is_negotiable: Optional[bool] = None
    is_valuable: Optional[bool] = None
    is_estimable: Optional[bool] = None
    is_small: Optional[bool] = None
    is_testable: Optional[bool] = None


class SprintAssignRequest(BaseSchema):
    """Request to assign a story to a sprint."""

    sprint_id: UUID


# ── Nested / embedded response schemas ────────────────────────────────────────


class TaskSummary(BaseSchema):
    """Minimal task summary embedded in UserStoryDetailResponse."""

    id: UUID
    task_number: str
    title: str
    status: str
    priority: str
    story_points: Optional[int] = None
    assignee_id: Optional[UUID] = None


class StoryApprovalSummary(BaseSchema):
    """Embedded approval state for a user story."""

    approval_id: Optional[UUID] = None
    status: Optional[ApprovalStatus] = None
    reviewer_id: Optional[UUID] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None


# ── Main response schemas ──────────────────────────────────────────────────────


class UserStoryResponse(BaseSchema):
    """Standard user story list-item response."""

    id: UUID
    organization_id: UUID
    project_id: UUID
    epic_id: Optional[UUID] = None
    requirement_id: Optional[UUID] = None
    current_sprint_id: Optional[UUID] = None
    story_number: str
    title: str
    as_a: Optional[str] = None
    i_want: Optional[str] = None
    so_that: Optional[str] = None
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    definition_of_done: Optional[str] = None
    status: StoryStatus
    priority: RequirementPriority
    story_points: Optional[int] = None
    business_value: Optional[int] = None
    is_ai_generated: bool
    ai_confidence_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="AI confidence score for this generated story",
    )
    # INVEST flags
    is_independent: Optional[bool] = None
    is_negotiable: Optional[bool] = None
    is_valuable: Optional[bool] = None
    is_estimable: Optional[bool] = None
    is_small: Optional[bool] = None
    is_testable: Optional[bool] = None
    # Denormalised aggregates
    task_count: int = Field(default=0)
    sprint_name: Optional[str] = Field(
        default=None,
        description="Name of the sprint this story is currently in",
    )
    tags: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None


class UserStoryDetailResponse(UserStoryResponse):
    """Extended user story response including tasks and approval info."""

    tasks: List[TaskSummary] = Field(default_factory=list)
    approval: Optional[StoryApprovalSummary] = None
    # Full acceptance criteria (may include structured list)
    acceptance_criteria_items: Optional[List[str]] = Field(
        default=None,
        description="Acceptance criteria split into a list of items",
    )
    metadata_: Optional[Dict[str, Any]] = Field(default=None, alias="metadata")


# ── Filters ────────────────────────────────────────────────────────────────────


class UserStoryFilter(BaseFilter):
    """Query parameters for filtering user story lists."""

    project_id: Optional[UUID] = None
    epic_id: Optional[UUID] = None
    status: Optional[StoryStatus] = None
    priority: Optional[RequirementPriority] = None
    sprint_id: Optional[UUID] = None
    is_ai_generated: Optional[bool] = None
    assignee_id: Optional[UUID] = None
    unassigned_to_sprint: Optional[bool] = Field(
        default=None,
        description="When true, return only stories not yet in any sprint",
    )
