"""Epic schemas – create, update, response, detail, bulk operations."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import Field, field_validator

from app.core.constants import ApprovalStatus, EpicStatus
from app.schemas.common import BaseFilter, BaseSchema


# ── Request schemas ────────────────────────────────────────────────────────────


class EpicCreate(BaseSchema):
    """Payload for creating a new epic."""

    title: str = Field(..., min_length=3, max_length=500)
    description: Optional[str] = Field(None, max_length=10_000)
    business_value: Optional[str] = Field(None, max_length=5_000)
    acceptance_criteria: Optional[str] = Field(None, max_length=10_000)
    priority: int = Field(default=50, ge=0, le=100, description="Priority score 0-100 (higher = more important)")
    story_points_estimate: Optional[int] = Field(None, ge=0, le=9999)
    estimated_effort: Optional[str] = Field(
        None,
        max_length=100,
        description="Free-text effort estimate, e.g. '2 sprints'",
    )
    start_date: Optional[str] = Field(None, description="ISO 8601 date string")
    target_date: Optional[str] = Field(None, description="ISO 8601 date string")
    requirement_ids: Optional[List[UUID]] = Field(
        default=None, description="Requirements this epic is derived from"
    )
    tags: Optional[List[str]] = Field(default=None, max_length=20)

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        return [t.strip().lower() for t in v if t and t.strip()]


class EpicUpdate(BaseSchema):
    """Partial-update payload for an existing epic."""

    title: Optional[str] = Field(None, min_length=3, max_length=500)
    description: Optional[str] = Field(None, max_length=10_000)
    business_value: Optional[str] = Field(None, max_length=5_000)
    acceptance_criteria: Optional[str] = Field(None, max_length=10_000)
    status: Optional[EpicStatus] = None
    priority: Optional[int] = Field(None, ge=0, le=100)
    story_points_estimate: Optional[int] = Field(None, ge=0, le=9999)
    story_points_actual: Optional[int] = Field(None, ge=0, le=9999)
    estimated_effort: Optional[str] = Field(None, max_length=100)
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    tags: Optional[List[str]] = None

    @field_validator("tags", mode="before")
    @classmethod
    def clean_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        return [t.strip().lower() for t in v if t and t.strip()]


class EpicBulkUpdate(BaseSchema):
    """Bulk status change for a set of epics."""

    epic_ids: List[UUID] = Field(..., min_length=1, max_length=200)
    status: EpicStatus


class EpicReorder(BaseSchema):
    """Ordered list of epic IDs defining the desired display order."""

    epic_ids: List[UUID] = Field(..., min_length=1)


# ── Response schemas ───────────────────────────────────────────────────────────


class EpicApprovalSummary(BaseSchema):
    """Embedded approval state for an epic."""

    approval_id: Optional[UUID] = None
    status: Optional[ApprovalStatus] = None
    reviewer_id: Optional[UUID] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None


class EpicResponse(BaseSchema):
    """Standard epic list-item response."""

    id: UUID
    organization_id: UUID
    project_id: UUID
    epic_number: str
    title: str
    description: Optional[str] = None
    business_value: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    status: EpicStatus
    priority: int
    story_points_estimate: Optional[int] = None
    story_points_actual: Optional[int] = None
    estimated_effort: Optional[str] = None
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    is_ai_generated: bool
    ai_confidence_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="AI confidence in this epic's accuracy"
    )
    # Aggregated counts (populated by the service layer via subquery)
    story_count: int = Field(default=0, description="Total user stories")
    approved_story_count: int = Field(default=0, description="Approved user stories")
    tags: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None
    created_by_name: Optional[str] = Field(
        default=None, description="Full name of the creator (denormalised)"
    )


class UserStorySummary(BaseSchema):
    """Minimal user story summary embedded in EpicDetailResponse."""

    id: UUID
    story_number: str
    title: str
    status: str
    priority: str
    story_points: Optional[int] = None
    current_sprint_id: Optional[UUID] = None


class EpicDetailResponse(EpicResponse):
    """Full epic response including related stories and approval info."""

    stories: List[UserStorySummary] = Field(default_factory=list)
    approval: Optional[EpicApprovalSummary] = None
    requirement_count: int = Field(
        default=0, description="Number of source requirements linked to this epic"
    )
    metadata_: Optional[dict[str, Any]] = Field(
        default=None, alias="metadata"
    )


# ── Filters ────────────────────────────────────────────────────────────────────


class EpicFilter(BaseFilter):
    """Query parameters for filtering epic lists."""

    project_id: Optional[UUID] = None
    status: Optional[EpicStatus] = None
    is_ai_generated: Optional[bool] = None
    min_priority: Optional[int] = Field(None, ge=0, le=100)
    max_priority: Optional[int] = Field(None, ge=0, le=100)
