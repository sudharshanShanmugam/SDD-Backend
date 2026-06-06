"""Document schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.core.constants import DocumentStatus
from app.schemas.common import BaseFilter, BaseSchema


class DocumentResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    project_id: UUID
    uploaded_by: Optional[UUID] = None
    original_filename: str
    content_type: str
    file_size_bytes: int
    status: DocumentStatus
    processing_error: Optional[str] = None
    page_count: Optional[int] = None
    word_count: Optional[int] = None
    language: Optional[str] = None
    extraction_confidence: Optional[float] = None
    version: int
    tags: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime


class DocumentUpdate(BaseSchema):
    tags: Optional[list[str]] = None
    metadata_: Optional[dict[str, Any]] = None


class DocumentFilter(BaseFilter):
    project_id: Optional[UUID] = None
    status: Optional[DocumentStatus] = None
    content_type: Optional[str] = None
    uploaded_by: Optional[UUID] = None
