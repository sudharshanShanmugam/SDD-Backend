"""Approval repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.models.approval import Approval, ApprovalComment
from app.repositories.base import BaseRepository


class ApprovalRepository(BaseRepository[Approval]):
    def __init__(self, db) -> None:
        super().__init__(db, Approval)

    async def list_by_org(
        self,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        resource_type: Optional[str] = None,
        requester_id: Optional[UUID] = None,
        reviewer_id: Optional[UUID] = None,
    ) -> tuple[list[Approval], int]:
        from sqlalchemy import desc

        stmt = (
            select(Approval)
            .where(Approval.organization_id == org_id)
        )
        if status:
            stmt = stmt.where(Approval.status == status)
        if resource_type:
            stmt = stmt.where(Approval.resource_type == resource_type)
        if requester_id:
            stmt = stmt.where(Approval.requester_id == requester_id)
        if reviewer_id:
            stmt = stmt.where(Approval.reviewer_id == reviewer_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(desc(Approval.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def get_for_resource(
        self, resource_type: str, resource_id: UUID, org_id: UUID
    ) -> Optional[Approval]:
        stmt = (
            select(Approval)
            .where(Approval.resource_type == resource_type)
            .where(Approval.resource_id == resource_id)
            .where(Approval.organization_id == org_id)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def add_comment(
        self,
        approval_id: UUID,
        author_id: UUID,
        body: str,
        is_internal: bool = False,
    ) -> ApprovalComment:
        import uuid

        comment = ApprovalComment(
            id=uuid.uuid4(),
            approval_id=approval_id,
            author_id=author_id,
            body=body,
            is_internal=is_internal,
        )
        self.db.add(comment)
        await self.db.flush()
        await self.db.refresh(comment)
        return comment

    async def complete_review(
        self,
        approval: Approval,
        status: str,
        reviewer_id: UUID,
        review_notes: Optional[str] = None,
        rejection_reason: Optional[str] = None,
    ) -> Approval:
        from datetime import datetime, timezone

        approval.status = status
        approval.reviewer_id = reviewer_id
        approval.reviewed_at = datetime.now(tz=timezone.utc).isoformat()
        approval.review_notes = review_notes
        approval.rejection_reason = rejection_reason
        await self.db.flush()
        await self.db.refresh(approval)
        return approval
