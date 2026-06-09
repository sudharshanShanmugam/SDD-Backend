"""Task model – engineering tasks within a user story."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import RequirementPriority, TaskStatus, TaskType
from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class Task(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_task_story", "user_story_id"),
        Index("ix_task_project", "project_id"),
        Index("ix_task_org", "organization_id"),
        Index("ix_task_assignee", "assignee_id"),
        Index("ix_task_status", "status"),
        Index("ix_task_sprint", "sprint_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_story_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_stories.id", ondelete="CASCADE"), nullable=True
    )
    sprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sprints.id", ondelete="SET NULL"), nullable=True
    )
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    parent_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )

    task_number: Mapped[str] = mapped_column(String(30), nullable=False)  # e.g. TASK-001
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_type: Mapped[TaskType] = mapped_column(
        String(50), nullable=False, default=TaskType.FEATURE
    )
    status: Mapped[TaskStatus] = mapped_column(
        String(50), nullable=False, default=TaskStatus.TODO, index=True
    )
    priority: Mapped[RequirementPriority] = mapped_column(
        String(50), nullable=False, default=RequirementPriority.MEDIUM
    )
    story_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    time_estimate_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_actual_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_remaining_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # YYYY-MM-DD
    started_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(nullable=False, default=False)
    ai_generation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_generations.id", ondelete="SET NULL"), nullable=True
    )
    tech_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pr_links: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    user_story: Mapped[Optional["UserStory"]] = relationship("UserStory", back_populates="tasks")
    assignee: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assignee_id], back_populates="assigned_tasks"
    )
    reporter: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[reporter_id], lazy="noload"
    )
    subtasks: Mapped[list["Task"]] = relationship(
        "Task", foreign_keys=[parent_task_id], back_populates="parent_task", lazy="noload"
    )
    parent_task: Mapped[Optional["Task"]] = relationship(
        "Task", foreign_keys=[parent_task_id], back_populates="subtasks", remote_side="Task.id"
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} num={self.task_number} status={self.status}>"


class TaskTimeLog(Base):
    """Individual time-log entries for a task."""
    __tablename__ = "task_time_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    hours: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logged_date: Mapped[str] = mapped_column(String(20), nullable=False)  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(tz=timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<TaskTimeLog id={self.id} task={self.task_id} hours={self.hours}>"


from app.models.user_story import UserStory  # noqa: E402
from app.models.user import User  # noqa: E402
