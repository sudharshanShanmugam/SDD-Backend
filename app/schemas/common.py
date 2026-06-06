"""Shared Pydantic v2 schema components used across the entire SDD API."""
from __future__ import annotations

import math
from typing import Any, Generic, List, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


# ── Base config ────────────────────────────────────────────────────────────────


class BaseSchema(BaseModel):
    """Common configuration inherited by all SDD schemas."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Pagination ─────────────────────────────────────────────────────────────────


class PaginationParams(BaseSchema):
    """Query-string parameters for paginated list endpoints."""

    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    size: int = Field(default=20, ge=1, le=100, description="Items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class PaginatedResponse(BaseSchema, Generic[T]):
    """Generic paginated list wrapper."""

    items: List[T]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    pages: int = Field(..., ge=0)
    has_next: bool
    has_prev: bool

    @classmethod
    def create(
        cls, items: List[T], total: int, page: int, page_size: int
    ) -> "PaginatedResponse[T]":
        pages = math.ceil(total / page_size) if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1,
        )


# ── Sort / Filter ──────────────────────────────────────────────────────────────


class SortOrder(str):
    ASC = "asc"
    DESC = "desc"


class SortParams(BaseSchema):
    """Generic sort parameters."""

    sort_by: str = Field(default="created_at")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")

    @property
    def is_desc(self) -> bool:
        return self.sort_order == "desc"


class BaseFilter(BaseSchema):
    """Common filter parameters shared by most list endpoints."""

    search: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None)
    priority: Optional[str] = Field(None)
    sort_by: Optional[str] = Field(None, max_length=100)
    sort_order: Optional[str] = Field("desc", pattern="^(asc|desc)$")
    include_deleted: bool = Field(default=False)

    @field_validator("search", mode="before")
    @classmethod
    def strip_search(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return v.strip() or None
        return v


# ── Simple response envelopes ──────────────────────────────────────────────────


class IDResponse(BaseSchema):
    """Minimal response returning only the affected entity UUID."""

    id: UUID


class MessageResponse(BaseSchema):
    """Plain acknowledgement."""

    message: str


class SuccessResponse(BaseSchema):
    """Generic boolean success envelope."""

    success: bool = True
    message: Optional[str] = None


# ── Error schemas ──────────────────────────────────────────────────────────────


class ErrorDetail(BaseSchema):
    """Field-level validation error."""

    error_code: str
    message: str
    detail: Optional[Any] = None
    field: Optional[str] = None


class ErrorResponse(BaseSchema):
    """Standard error envelope returned on 4xx / 5xx."""

    error: str
    message: str
    details: Optional[List[ErrorDetail]] = None
    request_id: Optional[str] = None


# ── Bulk helpers ───────────────────────────────────────────────────────────────


class BulkIDsRequest(BaseSchema):
    """Request body for bulk operations operating on a list of IDs."""

    ids: List[UUID] = Field(..., min_length=1, max_length=500)


class BulkUpdateResult(BaseSchema):
    """Result summary for bulk-update operations."""

    updated: int
    failed: int = 0
    errors: Optional[List[ErrorDetail]] = None


# ── Health-check ───────────────────────────────────────────────────────────────


class HealthResponse(BaseSchema):
    """Response for the /health endpoint."""

    status: str
    version: str
    environment: str
    database: str
    redis: str
    services: Optional[dict[str, str]] = None
