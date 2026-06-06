"""AIGeneration model – tracks every AI inference call."""
import uuid
from typing import Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import AIStatus
from app.models.base import Base, TimestampMixin


class AIGeneration(Base, TimestampMixin):
    __tablename__ = "ai_generations"
    __table_args__ = (
        Index("ix_ai_gen_project", "project_id"),
        Index("ix_ai_gen_org", "organization_id"),
        Index("ix_ai_gen_status", "status"),
        Index("ix_ai_gen_type", "generation_type"),
        Index("ix_ai_gen_initiated_by", "initiated_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    initiated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generation_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # requirement_extraction | epic_generation | story_generation | task_breakdown | qa_generation
    status: Mapped[AIStatus] = mapped_column(
        String(50), nullable=False, default=AIStatus.PENDING
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    input_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workflow_run_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="ai_generations")
    initiator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[initiated_by], lazy="noload")

    def __repr__(self) -> str:
        return f"<AIGeneration id={self.id} type={self.generation_type} status={self.status}>"


from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
