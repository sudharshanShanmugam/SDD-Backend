"""Approval and ApprovalComment models."""
import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ApprovalStatus
from app.models.base import Base, TimestampMixin


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approval_resource", "resource_type", "resource_id"),
        Index("ix_approval_org", "organization_id"),
        Index("ix_approval_reviewer", "reviewer_id"),
        Index("ix_approval_status", "status"),
        Index("ix_approval_requester", "requester_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # requirement, epic, story
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        String(50), nullable=False, default=ApprovalStatus.PENDING
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[str]] = mapped_column(nullable=True)
    reviewed_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    # Relationships
    requester: Mapped["User"] = relationship(
        "User", foreign_keys=[requester_id], lazy="noload"
    )
    reviewer: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[reviewer_id], lazy="noload"
    )
    comments: Mapped[list["ApprovalComment"]] = relationship(
        "ApprovalComment", back_populates="approval", lazy="noload", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Approval id={self.id} resource={self.resource_type}/{self.resource_id} status={self.status}>"


class ApprovalComment(Base, TimestampMixin):
    __tablename__ = "approval_comments"
    __table_args__ = (
        Index("ix_approval_comment_approval", "approval_id"),
        Index("ix_approval_comment_author", "author_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(nullable=False, default=False)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True, default=dict)

    approval: Mapped["Approval"] = relationship("Approval", back_populates="comments")
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id], lazy="noload")

    def __repr__(self) -> str:
        return f"<ApprovalComment id={self.id} approval={self.approval_id}>"


from app.models.user import User  # noqa: E402
