"""Epic model."""
import uuid
from typing import Optional

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import EpicStatus
from app.models.base import Base, TimestampMixin, SoftDeleteMixin

# Association table: epics ↔ requirements (M:M)
epic_requirements = Table(
    "epic_requirements",
    Base.metadata,
    Column("epic_id", UUID(as_uuid=True), ForeignKey("epics.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "requirement_id",
        UUID(as_uuid=True),
        ForeignKey("requirements.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Epic(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "epics"
    __table_args__ = (
        Index("ix_epic_project", "project_id"),
        Index("ix_epic_org", "organization_id"),
        Index("ix_epic_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    epic_number: Mapped[str] = mapped_column(String(30), nullable=False)  # e.g. EPIC-001
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[EpicStatus] = mapped_column(
        String(50), nullable=False, default=EpicStatus.DRAFT
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    story_points_estimate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    story_points_actual: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    start_date: Mapped[Optional[str]] = mapped_column(nullable=True)
    target_date: Mapped[Optional[str]] = mapped_column(nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(nullable=False, default=False)
    ai_generation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_generations.id", ondelete="SET NULL"), nullable=True
    )
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="epics")
    requirements: Mapped[list["Requirement"]] = relationship(
        "Requirement",
        secondary=epic_requirements,
        back_populates="epics",
        lazy="noload",
    )
    user_stories: Mapped[list["UserStory"]] = relationship(
        "UserStory", back_populates="epic", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Epic id={self.id} num={self.epic_number} status={self.status}>"


from app.models.project import Project  # noqa: E402
from app.models.requirement import Requirement  # noqa: E402
from app.models.user_story import UserStory  # noqa: E402
