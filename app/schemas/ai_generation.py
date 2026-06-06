"""AI Generation schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.core.constants import AIStatus
from app.schemas.common import BaseFilter, BaseSchema


class AIGenerationRequest(BaseSchema):
    generation_type: str = Field(
        min_length=1,
        max_length=100,
        description="One of: requirement_extraction, epic_generation, story_generation, task_breakdown, qa_generation",
    )
    document_ids: Optional[list[UUID]] = None
    requirement_ids: Optional[list[UUID]] = None
    epic_ids: Optional[list[UUID]] = None
    story_ids: Optional[list[UUID]] = None
    config_overrides: Optional[dict[str, Any]] = None


class AIGenerationResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    project_id: UUID
    initiated_by: Optional[UUID] = None
    generation_type: str
    status: AIStatus
    model_name: str
    model_version: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[int] = None
    confidence_score: Optional[float] = None
    error_message: Optional[str] = None
    retry_count: int
    celery_task_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AIGenerationFilter(BaseFilter):
    project_id: Optional[UUID] = None
    generation_type: Optional[str] = None
    status: Optional[AIStatus] = None
    initiated_by: Optional[UUID] = None
