"""WorkflowState model – LangGraph workflow state persistence."""
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class WorkflowState(Base, TimestampMixin):
    __tablename__ = "workflow_states"
    __table_args__ = (
        Index("ix_workflow_project", "project_id"),
        Index("ix_workflow_org", "organization_id"),
        Index("ix_workflow_run_id", "run_id"),
        Index("ix_workflow_type", "workflow_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    workflow_type: Mapped[str] = mapped_column(String(100), nullable=False)
    current_node: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_completed: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_failed: Mapped[bool] = mapped_column(nullable=False, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    checkpoint_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    graph_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    initiated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="workflow_states")

    def __repr__(self) -> str:
        return f"<WorkflowState id={self.id} run_id={self.run_id} type={self.workflow_type}>"


from app.models.project import Project  # noqa: E402
