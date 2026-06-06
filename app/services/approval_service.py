"""
Approval Service.
Approval workflow orchestration: queue management, approve/reject, history.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_approval(a) -> dict:
    """Serialize an Approval ORM object to a frontend-friendly dict."""
    def _str(v):
        return str(v) if v is not None else None

    status_raw = a.status
    if hasattr(status_raw, "value"):
        status_raw = status_raw.value

    return {
        "id": _str(a.id),
        # Map model field names → frontend expected names
        "entity_type": a.resource_type or "",
        "entity_id": _str(a.resource_id),
        "entity_title": a.title or "",
        "project_id": None,   # not a column on Approval
        "status": str(status_raw) if status_raw else "pending",
        "requested_by": _str(a.requester_id),
        "reviewer_id": _str(a.reviewer_id),
        "due_date": a.due_date,
        "priority": "medium",  # not a column on Approval
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


class ApprovalService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, approval_id: str):
        from app.models.approval import Approval
        try:
            approval_uuid = uuid.UUID(approval_id)
        except (ValueError, TypeError):
            return None
        return await self.db.get(Approval, approval_uuid)

    async def get_queue(
        self,
        reviewer_id: str,
        project_id: str | None,
        entity_type: str | None,
        priority: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.approval import Approval

        query = select(Approval).where(Approval.status == "pending")
        if reviewer_id:
            try:
                query = query.where(Approval.reviewer_id == uuid.UUID(reviewer_id))
            except (ValueError, TypeError):
                pass
        if entity_type:
            query = query.where(Approval.resource_type == entity_type)

        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(Approval.due_date.asc(), Approval.created_at.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_approval(a) for a in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def list_approvals(
        self,
        user_id: str,
        project_id: str | None,
        status: str | None,
        requested_by: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.approval import Approval

        query = select(Approval)
        if status:
            query = query.where(Approval.status == status)
        if requested_by:
            try:
                query = query.where(Approval.requester_id == uuid.UUID(requested_by))
            except (ValueError, TypeError):
                pass

        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(Approval.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_approval(a) for a in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def approve(
        self,
        approval_id: str,
        reviewer_id: str,
        comment: str | None,
    ) -> dict | None:
        from app.models.approval import Approval, ApprovalComment

        try:
            approval_uuid = uuid.UUID(approval_id)
            reviewer_uuid = uuid.UUID(reviewer_id)
        except (ValueError, TypeError):
            return None

        await self.db.execute(
            update(Approval)
            .where(Approval.id == approval_uuid)
            .values(
                status="approved",
                reviewer_id=reviewer_uuid,
                reviewed_at=datetime.now(tz=timezone.utc).isoformat(),
                updated_at=datetime.now(tz=timezone.utc),
            )
        )

        body = f"[approved]" + (f" {comment}" if comment else "")
        history = ApprovalComment(
            id=uuid.uuid4(),
            approval_id=approval_uuid,
            author_id=reviewer_uuid,
            body=body,
        )
        self.db.add(history)
        await self.db.commit()

        approval = await self.db.get(Approval, approval_uuid)
        await self._notify_status_change(approval, "approved", reviewer_id)
        return _serialize_approval(approval) if approval else None

    async def reject(
        self,
        approval_id: str,
        reviewer_id: str,
        reason: str,
        comment: str | None,
    ) -> dict | None:
        from app.models.approval import Approval, ApprovalComment

        try:
            approval_uuid = uuid.UUID(approval_id)
            reviewer_uuid = uuid.UUID(reviewer_id)
        except (ValueError, TypeError):
            return None

        await self.db.execute(
            update(Approval)
            .where(Approval.id == approval_uuid)
            .values(
                status="rejected",
                reviewer_id=reviewer_uuid,
                rejection_reason=reason,
                reviewed_at=datetime.now(tz=timezone.utc).isoformat(),
                updated_at=datetime.now(tz=timezone.utc),
            )
        )

        body = f"[rejected] Reason: {reason}" + (f"\n{comment}" if comment else "")
        history = ApprovalComment(
            id=uuid.uuid4(),
            approval_id=approval_uuid,
            author_id=reviewer_uuid,
            body=body,
        )
        self.db.add(history)
        await self.db.commit()

        approval = await self.db.get(Approval, approval_uuid)
        await self._notify_status_change(approval, "rejected", reviewer_id)
        return _serialize_approval(approval) if approval else None

    async def request_changes(
        self,
        approval_id: str,
        reviewer_id: str,
        reason: str,
        comment: str | None,
    ) -> dict | None:
        from app.models.approval import Approval, ApprovalComment

        try:
            approval_uuid = uuid.UUID(approval_id)
            reviewer_uuid = uuid.UUID(reviewer_id)
        except (ValueError, TypeError):
            return None

        await self.db.execute(
            update(Approval)
            .where(Approval.id == approval_uuid)
            .values(
                status="changes_requested",
                reviewer_id=reviewer_uuid,
                updated_at=datetime.now(tz=timezone.utc),
            )
        )

        body = f"[changes_requested] {reason}" + (f"\n{comment}" if comment else "")
        history = ApprovalComment(
            id=uuid.uuid4(),
            approval_id=approval_uuid,
            author_id=reviewer_uuid,
            body=body,
        )
        self.db.add(history)
        await self.db.commit()

        approval = await self.db.get(Approval, approval_uuid)
        return _serialize_approval(approval) if approval else None

    async def add_comment(
        self,
        approval_id: str,
        actor_id: str,
        comment: str,
    ) -> dict:
        from app.models.approval import ApprovalComment

        try:
            approval_uuid = uuid.UUID(approval_id)
            actor_uuid = uuid.UUID(actor_id)
        except (ValueError, TypeError):
            return {"message": "Invalid ID"}

        history = ApprovalComment(
            id=uuid.uuid4(),
            approval_id=approval_uuid,
            author_id=actor_uuid,
            body=comment,
        )
        self.db.add(history)
        await self.db.commit()
        await self.db.refresh(history)
        return {
            "id": str(history.id),
            "approval_id": str(history.approval_id),
            "actor_id": str(history.author_id),
            "comment": history.body,
            "created_at": history.created_at.isoformat() if history.created_at else None,
        }

    async def get_history(self, approval_id: str) -> list:
        from app.models.approval import ApprovalComment
        from app.models.user import User

        try:
            approval_uuid = uuid.UUID(approval_id)
        except (ValueError, TypeError):
            return []

        result = await self.db.execute(
            select(ApprovalComment, User)
            .join(User, User.id == ApprovalComment.author_id)
            .where(ApprovalComment.approval_id == approval_uuid)
            .order_by(ApprovalComment.created_at.asc())
        )
        return [
            {
                "id": str(h.id),
                "action": "comment",
                "actor_id": str(h.author_id),
                "actor_name": u.full_name,
                "comment": h.body,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h, u in result.all()
        ]

    async def _notify_status_change(self, approval, new_status: str, reviewer_id: str) -> None:
        """Send notification to the requester about approval status change."""
        logger.info(
            "Approval %s changed to %s by reviewer %s",
            approval.id if approval else "?",
            new_status,
            reviewer_id,
        )
