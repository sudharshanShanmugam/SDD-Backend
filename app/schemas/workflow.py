"""Workflow state schemas."""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from app.schemas.common import BaseSchema


class WorkflowStateResponse(BaseSchema):
    id: UUID
    organization_id: UUID
    project_id: UUID
    run_id: str
    workflow_type: str
    current_node: Optional[str] = None
    is_active: bool
    is_completed: bool
    is_failed: bool
    error_message: Optional[str] = None
    initiated_by: Optional[UUID] = None
    completed_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime
