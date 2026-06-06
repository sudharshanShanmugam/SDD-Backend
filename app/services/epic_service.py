"""
Epic Service – business logic for creating, updating, approving, and ordering epics.

This service sits between the API layer and the repository layer.  It handles:
  - Epic creation with auto-numbering and optional requirement linking
  - Update validation (status transitions, etc.)
  - Approval / rejection via the ApprovalService
  - Reordering (drag-and-drop kanban)
  - Rich detail retrieval with aggregated story counts
  - Audit logging via the AuditService
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ApprovalStatus, EpicStatus
from app.core.exceptions import (
    ApprovalError,
    EpicNotFoundError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
    WorkflowError,
)
from app.models.epic import Epic
from app.repositories.epic import EpicRepository

logger = logging.getLogger(__name__)


class EpicService:
    """
    Orchestrates all business logic for Epic entities.

    Parameters
    ----------
    db:
        AsyncSession injected from FastAPI dependency system.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._repo = EpicRepository(db)

    # ── CREATE ─────────────────────────────────────────────────────────────

    async def create_epic(
        self,
        project_id: UUID,
        org_id: UUID,
        data: Dict[str, Any],
        user_id: UUID,
    ) -> Epic:
        """
        Create a new epic in a project.

        Steps:
        1. Generate the next EPIC-NNNN number
        2. Persist the epic with ``is_ai_generated=False``
        3. Optionally link source requirements
        4. Flush within the caller's transaction (no commit here)

        Returns the new Epic ORM instance.
        """
        epic_number = await self._repo.get_next_number(project_id, org_id)

        # Extract requirement_ids before passing the rest to the ORM
        requirement_ids: Optional[List[UUID]] = data.pop("requirement_ids", None)

        epic = await self._repo.create(
            {
                **data,
                "project_id": project_id,
                "organization_id": org_id,
                "epic_number": epic_number,
                "is_ai_generated": False,
                "created_by": user_id,
                "updated_by": user_id,
            }
        )

        # Link requirements if provided
        if requirement_ids:
            await self._repo.link_requirements(epic.id, requirement_ids)

        logger.info("Epic %s created in project %s by user %s", epic.epic_number, project_id, user_id)
        return epic

    # ── READ ───────────────────────────────────────────────────────────────

    async def get_epic(
        self,
        epic_id: UUID,
        org_id: Optional[UUID] = None,
    ) -> Epic:
        """Fetch an epic by ID, raising EpicNotFoundError if absent."""
        epic = await self._repo.get_by_id(epic_id, org_id=org_id)
        if epic is None:
            raise EpicNotFoundError(message=f"Epic {epic_id} not found")
        return epic

    async def get_epic_with_stories(
        self,
        epic_id: UUID,
        org_id: Optional[UUID] = None,
    ) -> Epic:
        """
        Fetch an epic with its user stories eagerly loaded.

        Raises EpicNotFoundError if the epic does not exist.
        """
        epic = await self._repo.get_with_stories(epic_id, org_id=org_id)
        if epic is None:
            raise EpicNotFoundError(message=f"Epic {epic_id} not found")
        return epic

    async def list_epics(
        self,
        project_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[EpicStatus] = None,
        is_ai_generated: Optional[bool] = None,
        search: Optional[str] = None,
        sort_by: str = "priority",
        sort_order: str = "desc",
    ) -> Tuple[List[Epic], int]:
        """Return a paginated list of epics for a project."""
        return await self._repo.list_by_project(
            project_id=project_id,
            org_id=org_id,
            page=page,
            page_size=page_size,
            status=status,
            is_ai_generated=is_ai_generated,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_status_counts(
        self,
        project_id: UUID,
        org_id: Optional[UUID] = None,
    ) -> Dict[str, int]:
        """Return a count of epics per status for a project's dashboard."""
        return await self._repo.count_by_status(project_id, org_id=org_id)

    # ── UPDATE ─────────────────────────────────────────────────────────────

    async def update_epic(
        self,
        epic_id: UUID,
        data: Dict[str, Any],
        user_id: UUID,
        org_id: Optional[UUID] = None,
    ) -> Epic:
        """
        Update mutable fields on an epic.

        Enforces status transition rules:
        - CANCELLED epics cannot be updated (read-only)
        - COMPLETED epics can only be re-opened to ACTIVE
        """
        epic = await self.get_epic(epic_id, org_id=org_id)

        if epic.status == EpicStatus.CANCELLED:
            raise WorkflowError(
                message="Cannot update a cancelled epic. Restore it first."
            )

        new_status = data.get("status")
        if new_status and not self._is_valid_transition(epic.status, EpicStatus(new_status)):
            raise WorkflowError(
                message=f"Invalid status transition: {epic.status} → {new_status}"
            )

        update_data = {k: v for k, v in data.items() if v is not None}
        update_data["updated_by"] = user_id

        # Handle requirement link changes
        requirement_ids: Optional[List[UUID]] = update_data.pop("requirement_ids", None)

        updated = await self._repo.update_by_id(
            epic_id, org_id=org_id, updated_by=user_id, **update_data
        )
        if updated is None:
            raise EpicNotFoundError(message=f"Epic {epic_id} not found")

        if requirement_ids is not None:
            await self._repo.link_requirements(epic_id, requirement_ids)

        logger.info("Epic %s updated by user %s", epic_id, user_id)
        return updated

    # ── APPROVAL ───────────────────────────────────────────────────────────

    async def approve_epic(
        self,
        epic_id: UUID,
        reviewer_id: UUID,
        org_id: UUID,
        comment: Optional[str] = None,
    ):
        """
        Approve an epic.

        Creates or updates an Approval record and advances the epic's status
        to ACTIVE if it was DRAFT.

        Returns the updated Approval record.
        """
        epic = await self.get_epic(epic_id, org_id=org_id)

        if epic.status not in (EpicStatus.DRAFT, EpicStatus.ON_HOLD):
            raise ApprovalError(
                message=f"Epic in status '{epic.status}' cannot be approved"
            )

        # Persist approval record
        approval = await self._upsert_approval(
            resource_type="epic",
            resource_id=epic_id,
            org_id=org_id,
            reviewer_id=reviewer_id,
            status=ApprovalStatus.APPROVED,
            notes=comment,
        )

        # Advance epic status
        await self._repo.update_by_id(
            epic_id,
            org_id=org_id,
            updated_by=reviewer_id,
            status=EpicStatus.ACTIVE,
        )

        logger.info("Epic %s approved by %s", epic_id, reviewer_id)
        return approval

    async def reject_epic(
        self,
        epic_id: UUID,
        reviewer_id: UUID,
        org_id: UUID,
        reason: str,
    ):
        """
        Reject an epic with a mandatory reason.

        Returns the Approval record.
        """
        epic = await self.get_epic(epic_id, org_id=org_id)

        if not reason or not reason.strip():
            raise ValidationError(message="A rejection reason is required")

        approval = await self._upsert_approval(
            resource_type="epic",
            resource_id=epic_id,
            org_id=org_id,
            reviewer_id=reviewer_id,
            status=ApprovalStatus.REJECTED,
            notes=reason,
        )

        logger.info("Epic %s rejected by %s: %s", epic_id, reviewer_id, reason)
        return approval

    # ── REORDER ────────────────────────────────────────────────────────────

    async def reorder_epics(
        self,
        project_id: UUID,
        org_id: UUID,
        epic_ids: List[UUID],
    ) -> None:
        """
        Reorder epics within a project.

        ``epic_ids`` should be the complete ordered list of epic IDs as the
        user intends them to appear (index 0 = first / most important).
        """
        await self._repo.reorder(
            project_id=project_id,
            ordered_ids=epic_ids,
            org_id=org_id,
        )
        logger.debug("Reordered %d epics in project %s", len(epic_ids), project_id)

    # ── BULK ───────────────────────────────────────────────────────────────

    async def bulk_update_status(
        self,
        epic_ids: List[UUID],
        new_status: EpicStatus,
        org_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> int:
        """Bulk-update the status of multiple epics. Returns the count updated."""
        updated = await self._repo.bulk_update_status(
            epic_ids=epic_ids,
            new_status=new_status,
            org_id=org_id,
            updated_by=user_id,
        )
        logger.info("Bulk updated %d epics to status %s", updated, new_status)
        return updated

    # ── DELETE ─────────────────────────────────────────────────────────────

    async def delete_epic(
        self,
        epic_id: UUID,
        org_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> bool:
        """
        Soft-delete an epic.

        Returns True if the epic was found and deleted.
        """
        epic = await self.get_epic(epic_id, org_id=org_id)

        deleted = await self._repo.soft_delete(epic, deleted_by=user_id)
        if deleted:
            logger.info("Epic %s soft-deleted by user %s", epic_id, user_id)
        return bool(deleted)

    # ── AI creation helper ──────────────────────────────────────────────────

    async def bulk_create_from_ai(
        self,
        project_id: UUID,
        org_id: UUID,
        epics_data: List[Dict[str, Any]],
        ai_generation_id: Optional[UUID] = None,
        created_by: Optional[UUID] = None,
    ) -> List[Epic]:
        """
        Bulk-create epics produced by an AI generation run.

        Each dict in ``epics_data`` should contain at minimum ``title``.
        ``epic_number``, ``is_ai_generated``, and ``ai_generation_id`` are
        automatically set.
        """
        result: List[Epic] = []
        for item in epics_data:
            epic_number = await self._repo.get_next_number(project_id, org_id)
            epic = await self._repo.create(
                {
                    **item,
                    "project_id": project_id,
                    "organization_id": org_id,
                    "epic_number": epic_number,
                    "is_ai_generated": True,
                    "ai_generation_id": ai_generation_id,
                    "created_by": created_by,
                    "updated_by": created_by,
                }
            )
            result.append(epic)

        logger.info(
            "AI bulk-created %d epics in project %s (generation=%s)",
            len(result),
            project_id,
            ai_generation_id,
        )
        return result

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _upsert_approval(
        self,
        resource_type: str,
        resource_id: UUID,
        org_id: UUID,
        reviewer_id: UUID,
        status: ApprovalStatus,
        notes: Optional[str] = None,
    ):
        """
        Create or update an Approval record for an entity.

        Returns the Approval ORM instance.
        """
        from sqlalchemy import select
        from app.models.approval import Approval

        # Find existing pending approval
        existing = (
            await self.db.execute(
                select(Approval)
                .where(Approval.resource_type == resource_type)
                .where(Approval.resource_id == resource_id)
                .where(Approval.status.in_([ApprovalStatus.PENDING, ApprovalStatus.IN_REVIEW]))
            )
        ).scalar_one_or_none()

        now = datetime.now(tz=timezone.utc)

        if existing:
            existing.status = status
            existing.reviewer_id = reviewer_id
            existing.review_notes = notes
            existing.reviewed_at = now.isoformat()
            existing.updated_at = now
            await self.db.flush()
            return existing

        approval = Approval(
            organization_id=org_id,
            resource_type=resource_type,
            resource_id=resource_id,
            title=f"{resource_type.capitalize()} {resource_id}",
            reviewer_id=reviewer_id,
            requester_id=reviewer_id,
            status=status,
            review_notes=notes,
            reviewed_at=now.isoformat(),
        )
        self.db.add(approval)
        await self.db.flush()
        return approval

    @staticmethod
    def _is_valid_transition(current: EpicStatus, target: EpicStatus) -> bool:
        """
        Validate epic status transition rules.

        Allowed transitions::

            DRAFT      -> ACTIVE, CANCELLED, ON_HOLD
            ACTIVE     -> COMPLETED, CANCELLED, ON_HOLD, DRAFT
            ON_HOLD    -> ACTIVE, CANCELLED
            COMPLETED  -> ACTIVE (re-open)
            CANCELLED  -> (terminal – no transitions)
        """
        transitions: Dict[EpicStatus, set] = {
            EpicStatus.DRAFT: {EpicStatus.ACTIVE, EpicStatus.CANCELLED, EpicStatus.ON_HOLD},
            EpicStatus.ACTIVE: {
                EpicStatus.COMPLETED,
                EpicStatus.CANCELLED,
                EpicStatus.ON_HOLD,
                EpicStatus.DRAFT,
            },
            EpicStatus.ON_HOLD: {EpicStatus.ACTIVE, EpicStatus.CANCELLED},
            EpicStatus.COMPLETED: {EpicStatus.ACTIVE},
            EpicStatus.CANCELLED: set(),
        }
        return target in transitions.get(current, set())
