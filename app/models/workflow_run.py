"""WorkflowRun model – LangGraph workflow execution tracking with full state persistence."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class WorkflowRun(Base, TimestampMixin):
    """
    Tracks each LangGraph workflow execution from trigger through completion.

    Every AI pipeline run (requirement extraction, epic generation, etc.) creates
    a WorkflowRun record so we can resume failed runs, audit execution history,
    and surface progress to the UI via WebSocket.
    """
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_run_project", "project_id"),
        Index("ix_workflow_run_org", "organization_id"),
        Index("ix_workflow_run_type", "workflow_type"),
        Index("ix_workflow_run_status", "status"),
        Index("ix_workflow_run_triggered_by", "triggered_by"),
        Index("ix_workflow_run_document", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    triggered_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Workflow classification
    workflow_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment=(
            "requirement_extraction | epic_generation | story_generation | "
            "task_breakdown | qa_generation | sprint_planning | full_pipeline"
        ),
    )

    # Execution state
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | running | completed | failed | cancelled | paused",
    )
    current_stage: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Name of the currently-executing LangGraph node",
    )
    completed_stages: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
        comment="Ordered list of stage names that have completed successfully",
    )

    # Full LangGraph state snapshot – used for resumption
    state_data: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=dict,
        comment="Complete LangGraph state dict serialised at latest checkpoint",
    )

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Error info
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_trace: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Full Python traceback for debugging"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )

    # Progress metrics surfaced to UI
    total_steps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_percent: Mapped[Optional[float]] = mapped_column(nullable=True)

    # Output references
    output_summary: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment=(
            "High-level counts of what was generated, e.g. "
            '{"requirements": 12, "epics": 4, "stories": 24}'
        ),
    )

    # Extra context
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSONB, nullable=True, default=dict
    )

    # ── Relationships ────────────────────────────────────────────────────────

    project: Mapped["Project"] = relationship(
        "Project", back_populates="workflow_runs", lazy="noload"
    )
    document: Mapped[Optional["Document"]] = relationship(
        "Document", lazy="noload"
    )
    triggerer: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[triggered_by], lazy="noload"
    )

    # ── Convenience properties ───────────────────────────────────────────────

    @property
    def is_terminal(self) -> bool:
        """Return True if the run has reached a final state."""
        return self.status in {"completed", "failed", "cancelled"}

    @property
    def duration_seconds(self) -> Optional[float]:
        """Wall-clock duration if both start and end times are known."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def __repr__(self) -> str:
        return (
            f"<WorkflowRun id={self.id} type={self.workflow_type} "
            f"status={self.status} stage={self.current_stage}>"
        )


# Deferred imports to break circular dependency chains
from app.models.project import Project  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.user import User  # noqa: E402
