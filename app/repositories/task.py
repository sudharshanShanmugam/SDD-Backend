"""Task repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.models.task import Task
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    def __init__(self, db) -> None:
        super().__init__(db, Task)

    async def get_next_number(self, project_id: UUID, org_id: UUID) -> str:
        stmt = (
            select(func.count())
            .select_from(Task)
            .where(Task.project_id == project_id)
            .where(Task.organization_id == org_id)
        )
        count = (await self.db.execute(stmt)).scalar_one()
        return f"TASK-{count + 1:04d}"

    async def list_by_story(
        self,
        story_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 50,
        status: Optional[str] = None,
        assignee_id: Optional[UUID] = None,
    ) -> tuple[list[Task], int]:
        from sqlalchemy import asc

        stmt = (
            select(Task)
            .where(Task.user_story_id == story_id)
            .where(Task.organization_id == org_id)
            .where(Task.deleted_at.is_(None))
        )
        if status:
            stmt = stmt.where(Task.status == status)
        if assignee_id:
            stmt = stmt.where(Task.assignee_id == assignee_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(asc(Task.order_index), asc(Task.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def list_by_assignee(
        self,
        assignee_id: UUID,
        org_id: UUID,
        sprint_id: Optional[UUID] = None,
        status: Optional[str] = None,
    ) -> list[Task]:
        from sqlalchemy import desc

        stmt = (
            select(Task)
            .where(Task.assignee_id == assignee_id)
            .where(Task.organization_id == org_id)
            .where(Task.deleted_at.is_(None))
        )
        if sprint_id:
            stmt = stmt.where(Task.sprint_id == sprint_id)
        if status:
            stmt = stmt.where(Task.status == status)
        result = await self.db.execute(stmt.order_by(desc(Task.updated_at)))
        return list(result.scalars().all())

    async def assign(self, task: Task, assignee_id: UUID) -> Task:
        task.assignee_id = assignee_id
        await self.db.flush()
        await self.db.refresh(task)
        return task
