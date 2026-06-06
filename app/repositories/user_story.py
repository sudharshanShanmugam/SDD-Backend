"""
UserStory repository – domain-specific queries on top of BaseRepository.

Covers project/epic/sprint-scoped listing, sprint assignment, backlog queries,
and task-count aggregation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, asc, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import RequirementPriority, StoryStatus
from app.models.sprint import SprintUserStory
from app.models.task import Task
from app.models.user_story import UserStory
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class UserStoryRepository(BaseRepository[UserStory]):
    """
    Repository for UserStory entities.

    Inherits full CRUD + pagination from BaseRepository and adds
    sprint-planning helpers, epic-scoped queries, and task-count aggregation.
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db, UserStory)

    # ── Numbering ─────────────────────────────────────────────────────────────

    async def get_next_number(self, project_id: UUID, org_id: UUID) -> str:
        """Generate the next US-NNNN identifier (counts all, including deleted)."""
        stmt = (
            select(func.count())
            .select_from(UserStory)
            .where(UserStory.project_id == project_id)
            .where(UserStory.organization_id == org_id)
        )
        count = (await self.db.execute(stmt)).scalar_one()
        return f"US-{count + 1:04d}"

    # ── Project-scoped listing ────────────────────────────────────────────────

    async def list_by_project(
        self,
        project_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        epic_id: Optional[UUID] = None,
        status: Optional[StoryStatus] = None,
        priority: Optional[RequirementPriority] = None,
        sprint_id: Optional[UUID] = None,
        is_ai_generated: Optional[bool] = None,
        search: Optional[str] = None,
        unassigned_to_sprint: Optional[bool] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Tuple[List[UserStory], int]:
        """Return paginated user stories for a project with rich filter support."""
        stmt = (
            select(UserStory)
            .where(UserStory.project_id == project_id)
            .where(UserStory.organization_id == org_id)
            .where(UserStory.deleted_at.is_(None))
        )

        if epic_id is not None:
            stmt = stmt.where(UserStory.epic_id == epic_id)
        if status is not None:
            stmt = stmt.where(UserStory.status == status)
        if priority is not None:
            stmt = stmt.where(UserStory.priority == priority)
        if sprint_id is not None:
            stmt = stmt.where(UserStory.current_sprint_id == sprint_id)
        if is_ai_generated is not None:
            stmt = stmt.where(UserStory.is_ai_generated == is_ai_generated)
        if unassigned_to_sprint is True:
            stmt = stmt.where(UserStory.current_sprint_id.is_(None))
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    UserStory.title.ilike(pattern),
                    UserStory.story_number.ilike(pattern),
                    UserStory.description.ilike(pattern),
                )
            )

        # Count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self.db.execute(count_stmt)).scalar_one()

        # Order & paginate
        sort_col = getattr(UserStory, sort_by, UserStory.created_at)
        order_fn = desc if sort_order == "desc" else asc
        stmt = (
            stmt.order_by(order_fn(sort_col))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    # ── Epic-scoped listing ───────────────────────────────────────────────────

    async def list_by_epic(
        self,
        epic_id: UUID,
        org_id: Optional[UUID] = None,
        status: Optional[StoryStatus] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[UserStory], int]:
        """Return all stories belonging to a given epic."""
        stmt = (
            select(UserStory)
            .where(UserStory.epic_id == epic_id)
            .where(UserStory.deleted_at.is_(None))
        )
        if org_id is not None:
            stmt = stmt.where(UserStory.organization_id == org_id)
        if status is not None:
            stmt = stmt.where(UserStory.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self.db.execute(count_stmt)).scalar_one()

        stmt = (
            stmt.order_by(desc(UserStory.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    # ── Sprint-scoped listing ─────────────────────────────────────────────────

    async def list_by_sprint(
        self,
        sprint_id: UUID,
        org_id: Optional[UUID] = None,
        status: Optional[StoryStatus] = None,
    ) -> List[UserStory]:
        """Return all stories currently assigned to a sprint (no pagination needed
        since sprint size is naturally bounded)."""
        stmt = (
            select(UserStory)
            .where(UserStory.current_sprint_id == sprint_id)
            .where(UserStory.deleted_at.is_(None))
            .order_by(UserStory.story_number)
        )
        if org_id is not None:
            stmt = stmt.where(UserStory.organization_id == org_id)
        if status is not None:
            stmt = stmt.where(UserStory.status == status)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ── Sprint planning helpers ───────────────────────────────────────────────

    async def get_unassigned_stories(
        self,
        project_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 50,
        status: Optional[StoryStatus] = None,
        priority: Optional[RequirementPriority] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[UserStory], int]:
        """
        Return stories not yet assigned to any sprint (the sprint planning backlog).

        Ordered by: business_value desc, story_points asc (prioritise high-value,
        small stories – aligns with common sprint-planning heuristics).
        """
        stmt = (
            select(UserStory)
            .where(UserStory.project_id == project_id)
            .where(UserStory.organization_id == org_id)
            .where(UserStory.deleted_at.is_(None))
            .where(UserStory.current_sprint_id.is_(None))
        )
        if status is not None:
            stmt = stmt.where(UserStory.status == status)
        else:
            # Default: exclude done and cancelled from sprint planning backlog
            stmt = stmt.where(
                UserStory.status.not_in([StoryStatus.DONE, StoryStatus.CANCELLED])
            )
        if priority is not None:
            stmt = stmt.where(UserStory.priority == priority)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    UserStory.title.ilike(pattern),
                    UserStory.description.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await self.db.execute(count_stmt)).scalar_one()

        stmt = (
            stmt.order_by(
                desc(UserStory.business_value),
                asc(UserStory.story_points),
                desc(UserStory.created_at),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    # ── Sprint assignment ─────────────────────────────────────────────────────

    async def assign_to_sprint(
        self,
        story: UserStory,
        sprint_id: UUID,
        added_by: Optional[UUID] = None,
    ) -> UserStory:
        """Assign a story to a sprint, updating both the FK and the association table."""
        story.current_sprint_id = sprint_id
        story.updated_at = datetime.now(tz=timezone.utc)

        # Upsert the sprint_user_stories association row
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = (
            pg_insert(SprintUserStory)
            .values(
                sprint_id=sprint_id,
                user_story_id=story.id,
                added_by=added_by,
            )
            .on_conflict_do_nothing(constraint="uq_sprint_story")
        )
        await self.db.execute(stmt)
        await self.db.flush()
        await self.db.refresh(story)
        return story

    async def remove_from_sprint(
        self,
        story: UserStory,
        sprint_id: Optional[UUID] = None,
    ) -> UserStory:
        """Remove a story from its current sprint (or a specific sprint)."""
        from sqlalchemy import delete as sa_delete

        target_sprint_id = sprint_id or story.current_sprint_id
        story.current_sprint_id = None
        story.updated_at = datetime.now(tz=timezone.utc)

        if target_sprint_id is not None:
            await self.db.execute(
                sa_delete(SprintUserStory).where(
                    and_(
                        SprintUserStory.sprint_id == target_sprint_id,
                        SprintUserStory.user_story_id == story.id,
                    )
                )
            )
        await self.db.flush()
        await self.db.refresh(story)
        return story

    # ── Eager-loading ─────────────────────────────────────────────────────────

    async def get_with_tasks(
        self,
        story_id: UUID,
        org_id: Optional[UUID] = None,
    ) -> Optional[UserStory]:
        """Fetch a story with its tasks eagerly loaded."""
        stmt = (
            select(UserStory)
            .options(selectinload(UserStory.tasks))
            .where(UserStory.id == story_id)
            .where(UserStory.deleted_at.is_(None))
        )
        if org_id is not None:
            stmt = stmt.where(UserStory.organization_id == org_id)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ── Aggregation ───────────────────────────────────────────────────────────

    async def get_task_counts(
        self,
        story_ids: List[UUID],
    ) -> Dict[UUID, int]:
        """
        Return task counts per story for a batch of story IDs.

        Used to annotate UserStoryResponse objects without N+1 queries.
        """
        if not story_ids:
            return {}

        stmt = (
            select(Task.user_story_id, func.count(Task.id).label("cnt"))
            .where(Task.user_story_id.in_(story_ids))
            .where(Task.deleted_at.is_(None))
            .group_by(Task.user_story_id)
        )
        rows = (await self.db.execute(stmt)).all()
        return {row.user_story_id: row.cnt for row in rows}
