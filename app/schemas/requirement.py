"""Requirement schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.core.constants import ApprovalStatus, RequirementPriority, RequirementType
from app.schemas.common import BaseFilter, BaseSchema


class RequirementCreate(BaseSchema):
    title: str = Field(min_length=3, max_length=500)
    description: str = Field(min_length=1)
    acceptance_criteria: Optional[str] = None
    requirement_type: RequirementType = RequirementType.FUNCTIONAL
    priority: RequirementPriority = RequirementPriority.MEDIUM
    source_document_id: Optional[UUID] = None
    source_page: Optional[int] = None
    source_section: Optional[str] = None
    tags: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None


class RequirementUpdate(BaseSchema):
    title: Optional[str] = Field(None, min_length=3, max_length=500)
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    requirement_type: Optional[RequirementType] = None
    priority: Optional[RequirementPriority] = None
    status: Optional[ApprovalStatus] = None
    tags: Optional[list[str]] = None


class RequirementResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    project_id: UUID
    source_document_id: Optional[UUID] = None
    req_number: str
    title: str
    description: str
    acceptance_criteria: Optional[str] = None
    requirement_type: RequirementType
    priority: RequirementPriority
    status: ApprovalStatus
    confidence_score: Optional[float] = None
    source_page: Optional[int] = None
    source_section: Optional[str] = None
    is_ai_generated: bool
    tags: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime


class RequirementFilter(BaseFilter):
    project_id: Optional[UUID] = None
    requirement_type: Optional[RequirementType] = None
    priority: Optional[RequirementPriority] = None
    status: Optional[ApprovalStatus] = None
    is_ai_generated: Optional[bool] = None
    source_document_id: Optional[UUID] = None
