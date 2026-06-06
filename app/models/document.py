"""Document model – uploaded files and their processing state."""
import uuid
from typing import Optional

from sqlalchemy import BigInteger, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DocumentStatus
from app.models.base import Base, TimestampMixin, SoftDeleteMixin


class Document(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_doc_project", "project_id"),
        Index("ix_doc_org", "organization_id"),
        Index("ix_doc_status", "status"),
        Index("ix_doc_uploaded_by", "uploaded_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    s3_key: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    s3_bucket: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_md5: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    checksum_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(
        String(50), nullable=False, default=DocumentStatus.UPLOADED, index=True
    )
    processing_error: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(nullable=True)  # TEXT column
    parsed_content: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    vector_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    parent_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="documents")
    requirements: Mapped[list["Requirement"]] = relationship(
        "Requirement", back_populates="source_document", lazy="noload"
    )
    parent_document: Mapped[Optional["Document"]] = relationship(
        "Document", remote_side="Document.id", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} filename={self.original_filename} status={self.status}>"


from app.models.project import Project  # noqa: E402
from app.models.requirement import Requirement  # noqa: E402
