"""
Task Service.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_task(t) -> dict:
    """
    Serialize a Task ORM object to a frontend-friendly dict.

    Returns camelCase keys that match the TypeScript Task interface.
    The assignee relationship must be loaded before calling this (use
    selectinload(Task.assignee) in the query, or pass loaded=True).
    """
    def _str(v):
        return str(v) if v is not None else None

    status_raw = t.status
    if hasattr(status_raw, "value"):
        status_raw = status_raw.value

    priority_raw = t.priority
    if hasattr(priority_raw, "value"):
        priority_raw = priority_raw.value

    task_type_raw = t.task_type
    if hasattr(task_type_raw, "value"):
        task_type_raw = task_type_raw.value

    # Build assignee UserSummary if the relationship is already loaded
    assignee_obj = None
    try:
        if t.assignee is not None:
            u = t.assignee
            assignee_obj = {
                "id": str(u.id),
                "displayName": u.full_name or u.email,
                "email": u.email,
                "avatar": None,
            }
    except Exception:
        # Relationship not loaded — leave as None
        pass

    type_str   = str(task_type_raw) if task_type_raw else "development"
    status_str = str(status_raw)    if status_raw    else "todo"
    prio_str   = str(priority_raw)  if priority_raw  else "medium"

    return {
        # ── identity ──────────────────────────────────────────────────────────
        "id":             str(t.id),
        "identifier":     t.task_number or "",          # e.g. "TASK-001"
        "title":          t.title or "",
        "description":    t.description,
        # ── foreign keys (camelCase) ──────────────────────────────────────────
        "storyId":        _str(t.user_story_id),
        "projectId":      _str(t.project_id),
        "sprintId":       _str(getattr(t, "sprint_id", None)),
        "parentTaskId":   _str(t.parent_task_id),
        # ── status / meta ─────────────────────────────────────────────────────
        "status":         status_str,
        "priority":       prio_str,
        "type":           type_str,                     # matches TaskType
        # ── estimation ────────────────────────────────────────────────────────
        "estimatedHours": t.time_estimate_hours,
        "loggedHours":    t.time_actual_hours or 0,
        # ── people ────────────────────────────────────────────────────────────
        "assignee":       assignee_obj,
        "reporter":       None,                         # not tracked separately yet
        # ── misc ──────────────────────────────────────────────────────────────
        "tags":           t.tags or [],
        "isAiGenerated":  t.is_ai_generated,
        "sortOrder":      getattr(t, "position", 0) or 0,
        "isBlocked":      False,
        "blockedBy":      [],
        "subTasks":       [],
        "checklist":      [],
        "dueDate":        None,
        "startedAt":      None,
        "completedAt":    None,
        # ── audit ─────────────────────────────────────────────────────────────
        "createdAt":      t.created_at.isoformat() if t.created_at else None,
        "updatedAt":      t.updated_at.isoformat() if t.updated_at else None,
        # ── legacy snake_case aliases (kept for any old callers) ──────────────
        "task_number":    t.task_number or "",
        "task_type":      type_str,
        "estimated_hours":t.time_estimate_hours,
    }


class TaskService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_task(self, **kwargs) -> dict:
        from app.models.task import Task
        from app.models.user_story import UserStory

        # Map frontend field names → DB column names
        story_id_raw = kwargs.get("story_id")
        try:
            story_uuid = uuid.UUID(story_id_raw) if story_id_raw else None
        except (ValueError, TypeError):
            story_uuid = None

        # Get project_id, organization_id, and sprint_id from the story
        project_uuid = None
        org_uuid = None
        story_sprint_uuid = None
        if story_uuid:
            story = await self.db.get(UserStory, story_uuid)
            if story:
                project_uuid = story.project_id
                org_uuid = story.organization_id
                story_sprint_uuid = getattr(story, "current_sprint_id", None)

        # Auto-generate task_number
        count_result = await self.db.execute(
            select(func.count()).select_from(Task)
            .where(Task.user_story_id == story_uuid) if story_uuid else
            select(func.count()).select_from(Task)
        )
        task_count = count_result.scalar() or 0
        task_number = f"TASK-{task_count + 1:03d}"

        # Map estimated_hours → time_estimate_hours
        estimated_hours = kwargs.get("estimated_hours")

        # Map assignee_id
        assignee_id_raw = kwargs.get("assignee_id")
        try:
            assignee_uuid = uuid.UUID(assignee_id_raw) if assignee_id_raw else None
        except (ValueError, TypeError):
            assignee_uuid = None

        # Map parent_task_id
        parent_id_raw = kwargs.get("parent_task_id")
        try:
            parent_uuid = uuid.UUID(parent_id_raw) if parent_id_raw else None
        except (ValueError, TypeError):
            parent_uuid = None

        created_by_raw = kwargs.get("created_by")
        try:
            created_by_uuid = uuid.UUID(created_by_raw) if created_by_raw else None
        except (ValueError, TypeError):
            created_by_uuid = None

        task = Task(
            id=uuid.uuid4(),
            user_story_id=story_uuid,
            project_id=project_uuid,
            organization_id=org_uuid,
            sprint_id=story_sprint_uuid,  # inherit sprint from the parent story
            task_number=task_number,
            title=kwargs.get("title", ""),
            description=kwargs.get("description"),
            task_type=kwargs.get("task_type", "development"),
            priority=kwargs.get("priority", "medium"),
            status="todo",
            time_estimate_hours=estimated_hours,
            time_actual_hours=0.0,
            assignee_id=assignee_uuid,
            parent_task_id=parent_uuid,
            tags=kwargs.get("labels") or [],   # frontend sends "labels", model stores in "tags"
            is_ai_generated=False,
            created_by=created_by_uuid,
            updated_by=created_by_uuid,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return _serialize_task(task)

    async def get_by_id(self, task_id: str):
        from app.models.task import Task
        try:
            task_uuid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return None
        return await self.db.get(Task, task_uuid)

    async def list_tasks(
        self,
        user_id: str,
        story_id: str | None,
        sprint_id: str | None,
        project_id: str | None,
        assignee_id: str | None,
        status: str | None,
        priority: str | None,
        task_type: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.task import Task
        from app.models.user_story import UserStory
        from sqlalchemy.orm import selectinload

        # Eagerly load assignee so _serialize_task can build the UserSummary object
        query = (
            select(Task)
            .options(selectinload(Task.assignee))
            .where(Task.deleted_at.is_(None))
        )
        if project_id:
            try:
                query = query.where(Task.project_id == uuid.UUID(project_id))
            except (ValueError, TypeError):
                pass
        if story_id:
            try:
                query = query.where(Task.user_story_id == uuid.UUID(story_id))
            except (ValueError, TypeError):
                pass
        if sprint_id:
            try:
                sprint_uuid = uuid.UUID(sprint_id)
                query = (
                    query.join(UserStory, UserStory.id == Task.user_story_id)
                    .where(UserStory.current_sprint_id == sprint_uuid)
                )
            except (ValueError, TypeError):
                pass
        if assignee_id:
            try:
                query = query.where(Task.assignee_id == uuid.UUID(assignee_id))
            except (ValueError, TypeError):
                pass
        if status:
            query = query.where(Task.status == status)
        if priority:
            query = query.where(Task.priority == priority)
        if task_type:
            query = query.where(Task.task_type == task_type)

        total = (await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(Task.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_task(t) for t in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def update_task(self, task_id: str, data: dict, updated_by: str) -> dict | None:
        from app.models.task import Task

        try:
            task_uuid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return None

        # Map frontend field names → DB column names
        if "estimated_hours" in data:
            data["time_estimate_hours"] = data.pop("estimated_hours")
        if "actual_hours" in data:
            data["time_actual_hours"] = data.pop("actual_hours")
        if "labels" in data:
            data["tags"] = data.pop("labels")
        # story_id is read-only after creation; ignore if sent
        data.pop("story_id", None)

        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(
            update(Task).where(Task.id == task_uuid).values(**data)
        )
        await self.db.commit()
        task = await self.db.get(Task, task_uuid)
        return _serialize_task(task) if task else None

    async def delete_task(self, task_id: str) -> None:
        from app.models.task import Task
        try:
            task_uuid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return
        await self.db.execute(
            update(Task)
            .where(Task.id == task_uuid)
            .values(deleted_at=datetime.now(tz=timezone.utc))
        )
        await self.db.commit()

    async def move_task(
        self,
        task_id: str,
        new_status: str,
        position: int | None,
        moved_by: str,
    ) -> dict | None:
        updates: dict = {"status": new_status, "updated_at": datetime.now(tz=timezone.utc)}
        if new_status == "in_progress":
            updates["started_at"] = datetime.now(tz=timezone.utc)
        elif new_status == "done":
            updates["completed_at"] = datetime.now(tz=timezone.utc)
        if position is not None:
            updates["order_index"] = position
        return await self.update_task(task_id, updates, updated_by=moved_by)

    async def log_time(
        self,
        task_id: str,
        hours: float,
        description: str | None,
        user_id: str,
    ) -> dict:
        from app.models.task import Task

        try:
            task_uuid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return {"task_id": task_id, "hours_logged": hours, "total_hours": hours}

        # Update actual hours on task directly
        task = await self.db.get(Task, task_uuid)
        current_hours = task.time_actual_hours or 0.0 if task else 0.0
        total_logged = current_hours + hours

        await self.db.execute(
            update(Task)
            .where(Task.id == task_uuid)
            .values(
                time_actual_hours=total_logged,
                updated_at=datetime.now(tz=timezone.utc),
            )
        )
        await self.db.commit()
        return {"task_id": task_id, "hours_logged": hours, "total_hours": total_logged}
