"""
Task management API routes.
Task CRUD, kanban operations.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_project_access
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter()


class LogTimeRequest(BaseModel):
    hours: float = Field(ge=0.25, le=24)
    description: str | None = None
    loggedDate: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"))


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    story_id: str
    assignee_id: str | None = None
    priority: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    task_type: str = Field(default="development", pattern="^(development|design|testing|documentation|research|bug|devops|feature)$")
    estimated_hours: float | None = Field(default=None, ge=0, le=999)
    due_date: str | None = None
    labels: list[str] | None = None
    parent_task_id: str | None = None


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    assignee_id: str | None = None
    reporter_id: str | None = None
    priority: str | None = None
    status: str | None = None
    task_type: str | None = None
    estimated_hours: float | None = None
    actual_hours: float | None = None
    due_date: str | None = None
    labels: list[str] | None = None


class KanbanMoveRequest(BaseModel):
    status: str = Field(pattern="^(todo|in_progress|review|done|blocked)$")
    position: int | None = Field(default=None, ge=0)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create task",
)
async def create_task(
    payload: TaskCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import uuid as _uuid
    from sqlalchemy import select as _sa_select
    from app.models.user_story import UserStory as _UserStory

    try:
        story_uuid = _uuid.UUID(payload.story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story_id")

    _story_res = await db.execute(_sa_select(_UserStory).where(_UserStory.id == story_uuid))
    _story = _story_res.scalar_one_or_none()
    if not _story:
        raise HTTPException(status_code=404, detail="Story not found")

    await verify_project_access(db, project_id=str(_story.project_id), user_id=str(current_user.id))

    svc = TaskService(db)
    return await svc.create_task(
        **payload.model_dump(),
        created_by=str(current_user.id),
    )


@router.get(
    "",
    summary="List tasks",
)
async def list_tasks(
    project_id: str | None = Query(default=None),
    story_id: str | None = Query(default=None),
    sprint_id: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if project_id:
        await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))

    svc = TaskService(db)
    return await svc.list_tasks(
        user_id=str(current_user.id),
        project_id=project_id,
        story_id=story_id,
        sprint_id=sprint_id,
        assignee_id=assignee_id,
        status=status,
        priority=priority,
        task_type=task_type,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{task_id}",
    summary="Get task details",
)
async def get_task(
    task_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import uuid as _uuid
    from sqlalchemy import select as _select
    from sqlalchemy.orm import selectinload as _selectinload
    from app.models.task import Task as TaskModel
    from app.services.task_service import _serialize_task

    try:
        task_uuid = _uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid task_id.")

    # Use selectinload so the assignee/reporter relationships are populated for serialization
    result = await db.execute(
        _select(TaskModel)
        .options(_selectinload(TaskModel.assignee), _selectinload(TaskModel.reporter))
        .where(TaskModel.id == task_uuid, TaskModel.deleted_at.is_(None))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if task.project_id:
        await verify_project_access(db, project_id=str(task.project_id), user_id=str(current_user.id))
    return _serialize_task(task)


@router.patch(
    "/{task_id}",
    summary="Update task",
)
async def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = TaskService(db)
    task = await svc.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if task.project_id:
        await verify_project_access(db, project_id=str(task.project_id), user_id=str(current_user.id))
    return await svc.update_task(
        task_id=task_id,
        data=payload.model_dump(exclude_unset=True),
        updated_by=str(current_user.id),
    )


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete task",
)
async def delete_task(
    task_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = TaskService(db)
    task = await svc.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if task.project_id:
        await verify_project_access(db, project_id=str(task.project_id), user_id=str(current_user.id))
    await svc.delete_task(task_id=task_id)


@router.patch(
    "/{task_id}/move",
    summary="Move task on Kanban board",
)
async def move_task(
    task_id: str,
    payload: KanbanMoveRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change a task's status column on the Kanban board."""
    svc = TaskService(db)
    task = await svc.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if task.project_id:
        await verify_project_access(db, project_id=str(task.project_id), user_id=str(current_user.id))
    return await svc.move_task(
        task_id=task_id,
        new_status=payload.status,
        position=payload.position,
        moved_by=str(current_user.id),
    )


@router.post(
    "/{task_id}/log-time",
    summary="Log time spent on task",
)
async def log_time(
    task_id: str,
    hours: float = Query(ge=0.25, le=24),
    description: str | None = Query(default=None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log time spent working on a task."""
    svc = TaskService(db)
    task = await svc.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return await svc.log_time(
        task_id=task_id,
        hours=hours,
        description=description,
        user_id=str(current_user.id),
    )


# ── /tasks/{id}/time-logs  (REST endpoint the frontend expects) ───────────────

@router.get("/{task_id}/time-logs", summary="List time logs for a task")
async def list_time_logs(
    task_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.task import TaskTimeLog
    from app.models.user import User

    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid task_id")

    result = await db.execute(
        select(TaskTimeLog).where(TaskTimeLog.task_id == task_uuid).order_by(TaskTimeLog.created_at.desc())
    )
    logs = result.scalars().all()

    # Fetch user display names
    user_ids = list({log.user_id for log in logs if log.user_id})
    users: dict = {}
    if user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in u_res.scalars():
            users[str(u.id)] = getattr(u, "full_name", None) or getattr(u, "email", "Unknown")

    return [
        {
            "id": str(log.id),
            "taskId": str(log.task_id),
            "userId": str(log.user_id) if log.user_id else None,
            "user": {
                "id": str(log.user_id) if log.user_id else None,
                "displayName": users.get(str(log.user_id), "Unknown") if log.user_id else "Unknown",
            },
            "hours": log.hours,
            "description": log.description,
            "loggedDate": log.logged_date,
            "createdAt": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@router.post("/{task_id}/time-logs", summary="Log time on a task (REST)", status_code=201)
async def create_time_log(
    task_id: str,
    payload: LogTimeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.task import Task, TaskTimeLog

    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid task_id")

    task = await db.get(Task, task_uuid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    log = TaskTimeLog(
        id=uuid.uuid4(),
        task_id=task_uuid,
        user_id=current_user.id,
        hours=payload.hours,
        description=payload.description,
        logged_date=payload.loggedDate,
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(log)

    # Update accumulated hours on the task
    current = task.time_actual_hours or 0.0
    task.time_actual_hours = current + payload.hours
    await db.commit()
    await db.refresh(log)

    user_name = getattr(current_user, "full_name", None) or getattr(current_user, "email", "Unknown")
    return {
        "id": str(log.id),
        "taskId": task_id,
        "userId": str(current_user.id),
        "user": {"id": str(current_user.id), "displayName": user_name},
        "hours": log.hours,
        "description": log.description,
        "loggedDate": log.logged_date,
        "createdAt": log.created_at.isoformat(),
    }


@router.delete("/{task_id}/time-logs/{log_id}", summary="Delete a time log", status_code=204)
async def delete_time_log(
    task_id: str,
    log_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.task import Task, TaskTimeLog

    try:
        log_uuid = uuid.UUID(log_id)
        task_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid id")

    result = await db.execute(
        select(TaskTimeLog).where(TaskTimeLog.id == log_uuid, TaskTimeLog.task_id == task_uuid)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Time log not found.")

    # Deduct hours from task total
    task = await db.get(Task, task_uuid)
    if task and task.time_actual_hours:
        task.time_actual_hours = max(0.0, (task.time_actual_hours or 0.0) - log.hours)

    await db.execute(delete(TaskTimeLog).where(TaskTimeLog.id == log_uuid))
    await db.commit()
