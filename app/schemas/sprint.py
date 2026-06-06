"""Sprint schemas."""
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.core.constants import SprintStatus
from app.schemas.common import BaseFilter, BaseSchema


class SprintCreate(BaseSchema):
    name: str = Field(min_length=2, max_length=255)
    goal: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    capacity_points: Optional[int] = Field(None, ge=0)
    team_capacity_hours: Optional[float] = Field(None, ge=0)


class SprintUpdate(BaseSchema):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    goal: Optional[str] = None
    status: Optional[SprintStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    capacity_points: Optional[int] = Field(None, ge=0)
    committed_points: Optional[int] = Field(None, ge=0)
    completed_points: Optional[int] = Field(None, ge=0)
    team_capacity_hours: Optional[float] = Field(None, ge=0)
    review_notes: Optional[str] = None
    retrospective_notes: Optional[str] = None


class SprintResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    project_id: UUID
    sprint_number: int
    name: str
    goal: Optional[str] = None
    status: SprintStatus
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    capacity_points: Optional[int] = None
    committed_points: Optional[int] = None
    completed_points: Optional[int] = None
    velocity: Optional[float] = None
    team_capacity_hours: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class SprintAddStoriesRequest(BaseSchema):
    story_ids: list[UUID] = Field(min_length=1)


class SprintFilter(BaseFilter):
    project_id: Optional[UUID] = None
    status: Optional[SprintStatus] = None
