"""Sprint and SprintUserStory models."""
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Column, Date, Float, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import SprintStatus
from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class Sprint(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "sprints"
    __table_args__ = (
        Index("ix_sprint_project", "project_id"),
        Index("ix_sprint_org", "organization_id"),
        Index("ix_sprint_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    sprint_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[SprintStatus] = mapped_column(
        String(50), nullable=False, default=SprintStatus.PLANNING
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    capacity_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    committed_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    velocity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    team_capacity_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retrospective_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="sprints")
    story_associations: Mapped[list["SprintUserStory"]] = relationship(
        "SprintUserStory", back_populates="sprint", lazy="noload", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Sprint id={self.id} number={self.sprint_number} status={self.status}>"


class SprintUserStory(Base, TimestampMixin):
    """Association table tracking which stories belong to a sprint."""
    __tablename__ = "sprint_user_stories"
    __table_args__ = (
        UniqueConstraint("sprint_id", "user_story_id", name="uq_sprint_story"),
        Index("ix_sprint_story_sprint", "sprint_id"),
        Index("ix_sprint_story_story", "user_story_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sprints.id", ondelete="CASCADE"), nullable=False
    )
    user_story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_stories.id", ondelete="CASCADE"), nullable=False
    )
    added_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sprint: Mapped["Sprint"] = relationship("Sprint", back_populates="story_associations")
    user_story: Mapped["UserStory"] = relationship("UserStory", back_populates="sprint_associations")


from app.models.project import Project  # noqa: E402
from app.models.user_story import UserStory  # noqa: E402
