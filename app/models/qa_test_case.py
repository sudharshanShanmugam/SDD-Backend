"""QATestCase and QATestStep models."""
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import TestCasePriority, TestCaseStatus, TestCaseType
from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class QATestCase(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "qa_test_cases"
    __table_args__ = (
        Index("ix_qa_story", "user_story_id"),
        Index("ix_qa_project", "project_id"),
        Index("ix_qa_org", "organization_id"),
        Index("ix_qa_status", "status"),
        Index("ix_qa_type", "test_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_story_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_stories.id", ondelete="SET NULL"), nullable=True
    )
    requirement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )

    tc_number: Mapped[str] = mapped_column(String(30), nullable=False)  # TC-001
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preconditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    postconditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actual_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    test_type: Mapped[TestCaseType] = mapped_column(
        String(50), nullable=False, default=TestCaseType.FUNCTIONAL
    )
    status: Mapped[TestCaseStatus] = mapped_column(
        String(50), nullable=False, default=TestCaseStatus.DRAFT
    )
    priority: Mapped[TestCasePriority] = mapped_column(
        String(50), nullable=False, default=TestCasePriority.MEDIUM
    )
    estimated_duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_automated: Mapped[bool] = mapped_column(nullable=False, default=False)
    automation_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(nullable=False, default=False)
    ai_generation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_generations.id", ondelete="SET NULL"), nullable=True
    )
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    user_story: Mapped[Optional["UserStory"]] = relationship(
        "UserStory", back_populates="qa_test_cases"
    )
    steps: Mapped[list["QATestStep"]] = relationship(
        "QATestStep", back_populates="test_case", lazy="noload",
        cascade="all, delete-orphan", order_by="QATestStep.step_number"
    )

    def __repr__(self) -> str:
        return f"<QATestCase id={self.id} num={self.tc_number} type={self.test_type}>"


class QATestStep(Base, TimestampMixin):
    __tablename__ = "qa_test_steps"
    __table_args__ = (
        Index("ix_test_step_case", "test_case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("qa_test_cases.id", ondelete="CASCADE"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    expected_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    actual_outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    test_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    test_case: Mapped["QATestCase"] = relationship("QATestCase", back_populates="steps")

    def __repr__(self) -> str:
        return f"<QATestStep id={self.id} case={self.test_case_id} step={self.step_number}>"


from app.models.user_story import UserStory  # noqa: E402
