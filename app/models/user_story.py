"""UserStory model."""
import uuid
from typing import Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import RequirementPriority, StoryStatus
from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class UserStory(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "user_stories"
    __table_args__ = (
        Index("ix_story_project", "project_id"),
        Index("ix_story_epic", "epic_id"),
        Index("ix_story_org", "organization_id"),
        Index("ix_story_status", "status"),
        Index("ix_story_sprint", "current_sprint_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    epic_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("epics.id", ondelete="SET NULL"), nullable=True
    )
    requirement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )
    current_sprint_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sprints.id", ondelete="SET NULL"), nullable=True
    )

    story_number: Mapped[str] = mapped_column(String(30), nullable=False)  # e.g. US-001
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    # INVEST criteria
    as_a: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # "As a [user]"
    i_want: Mapped[Optional[str]] = mapped_column(Text, nullable=True)        # "I want [goal]"
    so_that: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # "So that [benefit]"
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    definition_of_done: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[StoryStatus] = mapped_column(
        String(50), nullable=False, default=StoryStatus.BACKLOG
    )
    priority: Mapped[RequirementPriority] = mapped_column(
        String(50), nullable=False, default=RequirementPriority.MEDIUM
    )
    story_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    business_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    time_estimate_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_actual_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(nullable=False, default=False)
    ai_generation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_generations.id", ondelete="SET NULL"), nullable=True
    )
    # INVEST flags
    is_independent: Mapped[Optional[bool]] = mapped_column(nullable=True)
    is_negotiable: Mapped[Optional[bool]] = mapped_column(nullable=True)
    is_valuable: Mapped[Optional[bool]] = mapped_column(nullable=True)
    is_estimable: Mapped[Optional[bool]] = mapped_column(nullable=True)
    is_small: Mapped[Optional[bool]] = mapped_column(nullable=True)
    is_testable: Mapped[Optional[bool]] = mapped_column(nullable=True)

    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    dependencies: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    epic: Mapped[Optional["Epic"]] = relationship("Epic", back_populates="user_stories")
    requirement: Mapped[Optional["Requirement"]] = relationship(
        "Requirement", back_populates="user_stories"
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="user_story", lazy="noload", cascade="all, delete-orphan"
    )
    sprint_associations: Mapped[list["SprintUserStory"]] = relationship(
        "SprintUserStory", back_populates="user_story", lazy="noload"
    )
    qa_test_cases: Mapped[list["QATestCase"]] = relationship(
        "QATestCase", back_populates="user_story", lazy="noload"
    )
    approvals: Mapped[list["Approval"]] = relationship(
        "Approval",
        primaryjoin="and_(Approval.resource_type=='user_story', foreign(Approval.resource_id)==UserStory.id)",
        lazy="noload",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<UserStory id={self.id} num={self.story_number} status={self.status}>"


from app.models.epic import Epic  # noqa: E402
from app.models.requirement import Requirement  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.sprint import SprintUserStory  # noqa: E402
from app.models.qa_test_case import QATestCase  # noqa: E402
from app.models.approval import Approval  # noqa: E402
