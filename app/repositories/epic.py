"""
Epic repository – domain-specific queries built on top of BaseRepository.

Covers project-scoped listing, story-count aggregations, bulk status updates,
epic reordering, and AI-generation linkage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, asc, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import EpicStatus
from app.models.epic import Epic
from app.models.user_story import UserStory
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class EpicRepository(BaseRepository[Epic]):
    """
    Repository for Epic entities.

    Inherits full CRUD + pagination from BaseRepository and adds
    project-scoped queries, story-count aggregations, and bulk operations.
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db, Epic)

    # ── Numbering helper ──────────────────────────────────────────────────────

    async def get_next_number(self, project_id: UUID, org_id: UUID) -> str:
        """Generate the next EPIC-NNNN identifier (counts all, including deleted)."""
        stmt = (
            select(func.count())
            .select_from(Epic)
            .where(Epic.project_id == project_id)
            .where(Epic.organization_id == org_id)
        )
        count = (await self.db.execute(stmt)).scalar_one()
        return f"EPIC-{count + 1:04d}"

    # ── Project-scoped listing ────────────────────────────────────────────────

    async def list_by_project(
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
        """
        Return paginated epics for a project.

        Defaults to descending priority so highest-priority epics appear first.
        Falls back to ``created_at`` descending as a secondary sort.
        """
        stmt = (
            select(Epic)
            .where(Epic.project_id == project_id)
            .where(Epic.organization_id == org_id)
            .where(Epic.deleted_at.is_(None))
        )

        if status is not None:
            stmt = stmt.where(Epic.status == status)
        if is_ai_generated is not None:
            stmt = stmt.where(Epic.is_ai_generated == is_ai_generated)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(Epic.title.ilike(pattern), Epic.description.ilike(pattern))
            )

        # Count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self.db.execute(count_stmt)).scalar_one()

        # Order & paginate
        sort_col = getattr(Epic, sort_by, Epic.priority)
        order_fn = desc if sort_order == "desc" else asc
        stmt = (
            stmt.order_by(order_fn(sort_col), desc(Epic.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    # ── Eager-loaded detail ───────────────────────────────────────────────────

    async def get_with_stories(
        self,
        epic_id: UUID,
        org_id: Optional[UUID] = None,
    ) -> Optional[Epic]:
        """
        Fetch an epic and eagerly load its user stories in one query.

        The ``user_stories`` relationship on the returned Epic instance is
        pre-populated, avoiding an N+1 on subsequent reads.
        """
        stmt = (
            select(Epic)
            .options(selectinload(Epic.user_stories))
            .where(Epic.id == epic_id)
            .where(Epic.deleted_at.is_(None))
        )
        if org_id is not None:
            stmt = stmt.where(Epic.organization_id == org_id)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ── Aggregation queries ───────────────────────────────────────────────────

    async def count_by_status(
        self,
        project_id: UUID,
        org_id: Optional[UUID] = None,
    ) -> Dict[str, int]:
        """
        Return a dict mapping each EpicStatus value to its count for a project.

        Example::

            {"draft": 3, "active": 12, "completed": 5, "cancelled": 1, "on_hold": 0}
        """
        stmt = (
            select(Epic.status, func.count(Epic.id).label("cnt"))
            .where(Epic.project_id == project_id)
            .where(Epic.deleted_at.is_(None))
            .group_by(Epic.status)
        )
        if org_id is not None:
            stmt = stmt.where(Epic.organization_id == org_id)

        rows = (await self.db.execute(stmt)).all()
        result: Dict[str, int] = {s.value: 0 for s in EpicStatus}
        for row in rows:
            result[row.status] = row.cnt
        return result

    async def get_story_counts(
        self,
        epic_ids: List[UUID],
    ) -> Dict[UUID, Dict[str, int]]:
        """
        Return total story counts per epic for a batch of epic IDs.

        Returns::

            {epic_id: {"total": 8, "done": 2}, ...}

        Use this to bulk-annotate EpicResponse objects without N+1 queries.
        """
        if not epic_ids:
            return {}

        from app.core.constants import StoryStatus

        stmt = (
            select(
                UserStory.epic_id,
                func.count(UserStory.id).label("total"),
            )
            .where(UserStory.epic_id.in_(epic_ids))
            .where(UserStory.deleted_at.is_(None))
            .group_by(UserStory.epic_id)
        )
        rows = (await self.db.execute(stmt)).all()

        counts: Dict[UUID, Dict[str, int]] = {
            eid: {"total": 0, "approved": 0, "done": 0} for eid in epic_ids
        }
        for row in rows:
            counts[row.epic_id]["total"] = row.total

        return counts

    # ── Bulk operations ───────────────────────────────────────────────────────

    async def bulk_update_status(
        self,
        epic_ids: List[UUID],
        new_status: EpicStatus,
        org_id: Optional[UUID] = None,
        updated_by: Optional[UUID] = None,
    ) -> int:
        """
        Set a new status on multiple epics in a single UPDATE statement.

        Returns the number of rows actually updated.
        """
        update_values: Dict[str, Any] = {
            "status": new_status,
            "updated_at": datetime.now(tz=timezone.utc),
        }
        if updated_by is not None:
            update_values["updated_by"] = updated_by

        conditions = [Epic.id.in_(epic_ids), Epic.deleted_at.is_(None)]
        if org_id is not None:
            conditions.append(Epic.organization_id == org_id)

        stmt = update(Epic).where(and_(*conditions)).values(**update_values)
        result = await self.db.execute(stmt)
        return result.rowcount

    async def reorder(
        self,
        project_id: UUID,
        ordered_ids: List[UUID],
        org_id: Optional[UUID] = None,
    ) -> None:
        """
        Update the ``priority`` of epics to reflect a new display order.

        ``ordered_ids`` is the desired order (index 0 = first / highest priority).
        Each epic's priority is set to ``len(ordered_ids) - index`` so that a
        descending-priority sort reproduces the intended order.
        """
        total = len(ordered_ids)
        for idx, epic_id in enumerate(ordered_ids):
            priority = total - idx
            conditions = [Epic.id == epic_id, Epic.project_id == project_id]
            if org_id is not None:
                conditions.append(Epic.organization_id == org_id)

            await self.db.execute(
                update(Epic)
                .where(and_(*conditions))
                .values(priority=priority, updated_at=datetime.now(tz=timezone.utc))
            )

    # ── Requirement association ───────────────────────────────────────────────

    async def link_requirements(
        self,
        epic_id: UUID,
        requirement_ids: List[UUID],
    ) -> None:
        """Associate source requirements with an epic (idempotent via ON CONFLICT DO NOTHING)."""
        from app.models.epic import epic_requirements
        from sqlalchemy.dialects.postgresql import insert

        for req_id in requirement_ids:
            stmt = (
                insert(epic_requirements)
                .values(epic_id=epic_id, requirement_id=req_id)
                .on_conflict_do_nothing()
            )
            await self.db.execute(stmt)
        await self.db.flush()

    async def unlink_requirements(
        self,
        epic_id: UUID,
        requirement_ids: List[UUID],
    ) -> None:
        """Remove specific requirement associations from an epic."""
        from sqlalchemy import delete as sa_delete
        from app.models.epic import epic_requirements

        stmt = (
            sa_delete(epic_requirements)
            .where(epic_requirements.c.epic_id == epic_id)
            .where(epic_requirements.c.requirement_id.in_(requirement_ids))
        )
        await self.db.execute(stmt)
        await self.db.flush()
