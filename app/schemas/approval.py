"""Approval schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.core.constants import ApprovalStatus
from app.schemas.common import BaseFilter, BaseSchema


class ApprovalCreate(BaseSchema):
    resource_type: str = Field(min_length=1, max_length=50)
    resource_id: UUID
    title: str = Field(min_length=3, max_length=500)
    description: Optional[str] = None
    reviewer_id: Optional[UUID] = None
    due_date: Optional[str] = None


class ApprovalReview(BaseSchema):
    status: ApprovalStatus
    review_notes: Optional[str] = None
    rejection_reason: Optional[str] = None


class ApprovalCommentCreate(BaseSchema):
    body: str = Field(min_length=1, max_length=5000)
    is_internal: bool = False


class ApprovalCommentResponse(BaseSchema):
    id: UUID
    approval_id: UUID
    author_id: UUID
    body: str
    is_internal: bool
    created_at: datetime


class ApprovalResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    resource_type: str
    resource_id: UUID
    requester_id: UUID
    reviewer_id: Optional[UUID] = None
    status: ApprovalStatus
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ApprovalFilter(BaseFilter):
    resource_type: Optional[str] = None
    resource_id: Optional[UUID] = None
    requester_id: Optional[UUID] = None
    reviewer_id: Optional[UUID] = None
    status: Optional[ApprovalStatus] = None
