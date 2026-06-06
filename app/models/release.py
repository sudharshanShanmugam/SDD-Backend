"""Release and ReleaseItem models."""
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ReleaseStatus
from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class Release(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "releases"
    __table_args__ = (
        Index("ix_release_project", "project_id"),
        Index("ix_release_org", "organization_id"),
        Index("ix_release_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)  # semver e.g. 1.2.0
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ReleaseStatus] = mapped_column(
        String(50), nullable=False, default=ReleaseStatus.PLANNING
    )
    target_date: Mapped[Optional[str]] = mapped_column(nullable=True)
    released_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="releases")
    items: Mapped[list["ReleaseItem"]] = relationship(
        "ReleaseItem", back_populates="release", lazy="noload", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Release id={self.id} version={self.version} status={self.status}>"


class ReleaseItem(Base, TimestampMixin):
    __tablename__ = "release_items"
    __table_args__ = (
        Index("ix_release_item_release", "release_id"),
        Index("ix_release_item_resource", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # epic | story | task
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    release: Mapped["Release"] = relationship("Release", back_populates="items")


from app.models.project import Project  # noqa: E402
