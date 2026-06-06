"""Sprint repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.models.sprint import Sprint, SprintUserStory
from app.repositories.base import BaseRepository


class SprintRepository(BaseRepository[Sprint]):
    def __init__(self, db) -> None:
        super().__init__(db, Sprint)

    async def get_next_number(self, project_id: UUID) -> int:
        stmt = (
            select(func.coalesce(func.max(Sprint.sprint_number), 0))
            .where(Sprint.project_id == project_id)
        )
        max_num = (await self.db.execute(stmt)).scalar_one()
        return max_num + 1

    async def get_active_sprint(self, project_id: UUID) -> Optional[Sprint]:
        from app.core.constants import SprintStatus

        stmt = (
            select(Sprint)
            .where(Sprint.project_id == project_id)
            .where(Sprint.status == SprintStatus.ACTIVE)
            .where(Sprint.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_by_project(
        self,
        project_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> tuple[list[Sprint], int]:
        from sqlalchemy import asc

        stmt = (
            select(Sprint)
            .where(Sprint.project_id == project_id)
            .where(Sprint.organization_id == org_id)
            .where(Sprint.deleted_at.is_(None))
        )
        if status:
            stmt = stmt.where(Sprint.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(asc(Sprint.sprint_number)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def add_story(
        self, sprint_id: UUID, story_id: UUID, added_by: Optional[UUID] = None
    ) -> SprintUserStory:
        import uuid

        # Check for existing association
        stmt = (
            select(SprintUserStory)
            .where(SprintUserStory.sprint_id == sprint_id)
            .where(SprintUserStory.user_story_id == story_id)
        )
        existing = (await self.db.execute(stmt)).scalars().first()
        if existing:
            return existing

        assoc = SprintUserStory(
            id=uuid.uuid4(),
            sprint_id=sprint_id,
            user_story_id=story_id,
            added_by=added_by,
        )
        self.db.add(assoc)
        await self.db.flush()
        return assoc

    async def remove_story(self, sprint_id: UUID, story_id: UUID) -> bool:
        stmt = (
            select(SprintUserStory)
            .where(SprintUserStory.sprint_id == sprint_id)
            .where(SprintUserStory.user_story_id == story_id)
        )
        assoc = (await self.db.execute(stmt)).scalars().first()
        if assoc:
            await self.db.delete(assoc)
            await self.db.flush()
            return True
        return False
