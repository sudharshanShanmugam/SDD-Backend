"""
Story Service.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class StoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_story(self, **kwargs) -> object:
        from app.models.story import Story
        story = Story(
            id=str(uuid.uuid4()),
            status="backlog",
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
            **kwargs,
        )
        self.db.add(story)
        await self.db.commit()
        await self.db.refresh(story)
        return story

    async def get_by_id(self, story_id: str):
        from app.models.story import Story
        result = await self.db.execute(select(Story).where(Story.id == story_id))
        return result.scalar_one_or_none()

    async def list_stories(
        self,
        user_id: str,
        epic_id: str | None,
        sprint_id: str | None,
        assignee_id: str | None,
        status: str | None,
        priority: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.story import Story

        query = select(Story)
        if epic_id:
            query = query.where(Story.epic_id == epic_id)
        if sprint_id:
            query = query.where(Story.current_sprint_id == sprint_id)
        if assignee_id:
            query = query.where(Story.assignee_id == assignee_id)
        if status:
            query = query.where(Story.status == status)
        if priority:
            query = query.where(Story.priority == priority)

        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(Story.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def update_story(self, story_id: str, data: dict, updated_by: str):
        from app.models.story import Story
        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(update(Story).where(Story.id == story_id).values(**data))
        await self.db.commit()
        return await self.get_by_id(story_id)

    async def delete_story(self, story_id: str) -> None:
        from app.models.story import Story
        from sqlalchemy import delete as sql_delete
        await self.db.execute(sql_delete(Story).where(Story.id == story_id))
        await self.db.commit()

    async def assign_sprint(self, story_id: str, sprint_id: str | None):
        return await self.update_story(story_id, {"sprint_id": sprint_id}, updated_by="")

    async def get_tasks(self, story_id: str) -> list:
        from app.models.task import Task
        from sqlalchemy.orm import selectinload
        from app.services.task_service import _serialize_task
        try:
            story_uuid = uuid.UUID(story_id)
        except (ValueError, TypeError):
            return []
        result = await self.db.execute(
            select(Task)
            .options(selectinload(Task.assignee))
            .where(Task.user_story_id == story_uuid, Task.deleted_at.is_(None))
            .order_by(Task.created_at)
        )
        tasks = result.scalars().all()
        return [_serialize_task(t) for t in tasks]
