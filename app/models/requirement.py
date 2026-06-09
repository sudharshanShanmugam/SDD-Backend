"""Requirement model – extracted/authored requirements."""
import uuid
from typing import Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ApprovalStatus, RequirementPriority, RequirementType
from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class Requirement(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "requirements"
    __table_args__ = (
        Index("ix_req_project", "project_id"),
        Index("ix_req_org", "organization_id"),
        Index("ix_req_type", "requirement_type"),
        Index("ix_req_priority", "priority"),
        Index("ix_req_status", "status"),
        Index("ix_req_document", "source_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    req_number: Mapped[str] = mapped_column(String(30), nullable=False)  # e.g. REQ-001
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requirement_type: Mapped[RequirementType] = mapped_column(
        String(50), nullable=False, default=RequirementType.FUNCTIONAL
    )
    priority: Mapped[RequirementPriority] = mapped_column(
        String(50), nullable=False, default=RequirementPriority.MEDIUM
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        String(50), nullable=False, default=ApprovalStatus.PENDING
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_section: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_ai_generated: Mapped[bool] = mapped_column(nullable=False, default=False)
    ai_generation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_generations.id", ondelete="SET NULL"), nullable=True
    )
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    dependencies: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="requirements")
    source_document: Mapped[Optional["Document"]] = relationship(
        "Document", back_populates="requirements"
    )
    user_stories: Mapped[list["UserStory"]] = relationship(
        "UserStory", back_populates="requirement", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Requirement id={self.id} num={self.req_number} type={self.requirement_type}>"


from app.models.project import Project  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.user_story import UserStory  # noqa: E402
