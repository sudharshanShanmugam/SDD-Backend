"""Project and ProjectMember models."""
import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import UserRole, WorkflowStage
from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class Project(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_project_workspace", "workspace_id"),
        Index("ix_project_org", "organization_id"),
        Index("ix_project_stage", "workflow_stage"),
        Index("ix_project_org_key", "organization_id", "key", postgresql_where="deleted_at IS NULL"),
        UniqueConstraint("organization_id", "key", name="uq_project_org_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "SDD"
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    workflow_stage: Mapped[WorkflowStage] = mapped_column(
        String(50), nullable=False, default=WorkflowStage.DOCUMENT_UPLOAD
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    start_date: Mapped[Optional[str]] = mapped_column(nullable=True)
    target_date: Mapped[Optional[str]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ai_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="projects")
    members: Mapped[list["ProjectMember"]] = relationship(
        "ProjectMember", back_populates="project", lazy="noload", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="project", lazy="noload"
    )
    requirements: Mapped[list["Requirement"]] = relationship(
        "Requirement", back_populates="project", lazy="noload"
    )
    epics: Mapped[list["Epic"]] = relationship("Epic", back_populates="project", lazy="noload")
    sprints: Mapped[list["Sprint"]] = relationship("Sprint", back_populates="project", lazy="noload")
    ai_generations: Mapped[list["AIGeneration"]] = relationship(
        "AIGeneration", back_populates="project", lazy="noload"
    )
    workflow_states: Mapped[list["WorkflowState"]] = relationship(
        "WorkflowState", back_populates="project", lazy="noload"
    )
    releases: Mapped[list["Release"]] = relationship(
        "Release", back_populates="project", lazy="noload"
    )
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(
        "WorkflowRun", back_populates="project", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} key={self.key} stage={self.workflow_stage}>"


class ProjectMember(Base, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        Index("ix_project_member_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[UserRole] = mapped_column(String(50), nullable=False, default=UserRole.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    project: Mapped["Project"] = relationship("Project", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="project_memberships")


from app.models.workspace import Workspace  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.requirement import Requirement  # noqa: E402
from app.models.epic import Epic  # noqa: E402
from app.models.sprint import Sprint  # noqa: E402
from app.models.ai_generation import AIGeneration  # noqa: E402
from app.models.workflow import WorkflowState  # noqa: E402
from app.models.release import Release  # noqa: E402
from app.models.workflow_run import WorkflowRun  # noqa: E402
