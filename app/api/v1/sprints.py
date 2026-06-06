"""
Sprint management API routes.
Sprint planning, velocity, capacity.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_project_access
from app.services.sprint_service import SprintService, _serialize_sprint

logger = logging.getLogger(__name__)
router = APIRouter()


class SprintCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    project_id: str
    goal: str | None = None
    start_date: str
    end_date: str
    capacity_points: int | None = Field(default=None, ge=0, le=1000)


class SprintUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    goal: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    capacity_points: int | None = None
    status: str | None = None


class StartSprintRequest(BaseModel):
    goal: str | None = None


class CompleteSprintRequest(BaseModel):
    incomplete_story_action: str = Field(
        default="backlog",
        pattern="^(backlog|next_sprint)$",
        description="Where to move incomplete stories: backlog or next sprint",
    )
    next_sprint_id: str | None = None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create sprint",
)
async def create_sprint(
    payload: SprintCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(db, project_id=payload.project_id, user_id=str(current_user.id))
    svc = SprintService(db)
    try:
        return await svc.create_sprint(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "",
    summary="List sprints",
)
async def list_sprints(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if project_id:
        await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    svc = SprintService(db)
    return await svc.list_sprints(
        user_id=str(current_user.id),
        project_id=project_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{sprint_id}",
    summary="Get sprint details (includes stories for the Kanban board)",
)
async def get_sprint(
    sprint_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select as _select
    from app.models.user_story import UserStory
    from app.api.v1.stories import _serialize_story

    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")

    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))

    result = _serialize_sprint(sprint)

    # ── Attach stories so the Kanban board has all the data it needs ──────────
    stories_q = await db.execute(
        _select(UserStory)
        .where(
            UserStory.current_sprint_id == sprint.id,
            UserStory.deleted_at.is_(None),
        )
        .order_by(UserStory.story_points.desc().nullslast())
    )
    stories = list(stories_q.scalars().all())

    total_pts = sum(s.story_points or 0 for s in stories)
    done_pts = sum(
        s.story_points or 0 for s in stories
        if str(s.status.value if hasattr(s.status, "value") else s.status) == "done"
    )

    result["stories"] = [_serialize_story(s) for s in stories]
    result["storyCount"] = len(stories)
    result["totalStoryPoints"] = total_pts
    result["completedStoryPoints"] = done_pts

    # Provide Sprint (full) fields that SprintBoardPage / SprintMetrics expect
    result.setdefault("burndownData", [])
    result.setdefault("capacity", [])
    result.setdefault("retrospective", None)
    result.setdefault("completedDate", None)
    result.setdefault("owner", None)
    result["isActive"] = result.get("status") == "active"

    return result


@router.patch(
    "/{sprint_id}",
    summary="Update sprint",
)
async def update_sprint(
    sprint_id: str,
    payload: SprintUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")

    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))

    sprint_status = str(sprint.status.value if hasattr(sprint.status, "value") else sprint.status)
    if sprint_status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify a completed sprint.",
        )
    return await svc.update_sprint(
        sprint_id=sprint_id,
        data=payload.model_dump(exclude_none=True),
    )


@router.delete(
    "/{sprint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete sprint",
)
async def delete_sprint(
    sprint_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")

    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))

    sprint_status = str(sprint.status.value if hasattr(sprint.status, "value") else sprint.status)
    if sprint_status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completed sprints cannot be deleted.",
        )
    await svc.delete_sprint(sprint_id=sprint_id)


@router.post(
    "/{sprint_id}/start",
    summary="Start sprint",
)
async def start_sprint(
    sprint_id: str,
    payload: StartSprintRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a planning sprint."""
    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")

    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))

    sprint_status = str(sprint.status.value if hasattr(sprint.status, "value") else sprint.status)
    if sprint_status not in ("planning", "planned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only planning sprints can be started.",
        )
    return await svc.start_sprint(
        sprint_id=sprint_id,
        goal=payload.goal,
        started_by=str(current_user.id),
    )


@router.post(
    "/{sprint_id}/complete",
    summary="Complete sprint",
)
async def complete_sprint(
    sprint_id: str,
    payload: CompleteSprintRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a sprint as completed. Handles incomplete stories."""
    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")

    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))

    sprint_status = str(sprint.status.value if hasattr(sprint.status, "value") else sprint.status)
    if sprint_status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only active sprints can be completed.",
        )
    return await svc.complete_sprint(
        sprint_id=sprint_id,
        incomplete_action=payload.incomplete_story_action,
        next_sprint_id=payload.next_sprint_id,
        completed_by=str(current_user.id),
    )


@router.get(
    "/{sprint_id}/velocity",
    summary="Get sprint velocity and burndown data",
)
async def get_sprint_velocity(
    sprint_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return velocity metrics, burndown chart data, and team capacity."""
    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")
    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))
    return await svc.get_velocity_data(sprint_id=sprint_id)


@router.get(
    "/{sprint_id}/board",
    summary="Get kanban board data for sprint",
)
async def get_sprint_board(
    sprint_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all stories and tasks grouped by status for the Kanban board."""
    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")
    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))
    return await svc.get_board_data(sprint_id=sprint_id)


@router.post(
    "/clear-plan",
    status_code=status.HTTP_200_OK,
    summary="Delete all planning sprints for a project and unassign their stories",
)
async def clear_sprint_plan(
    project_id: str = Query(..., description="Project UUID"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk-reset sprint planning for a project:
    1. Finds all sprints (any status).
    2. Sets current_sprint_id = NULL on every story in those sprints.
    3. Soft-deletes the sprint rows.
    Returns a summary of what was cleared.
    """
    import uuid as _uuid
    from datetime import datetime, timezone
    from sqlalchemy import select as _select, update as _update
    from app.models.sprint import Sprint
    from app.models.user_story import UserStory

    try:
        project_uuid = _uuid.UUID(project_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid project_id.")

    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))

    now = datetime.now(tz=timezone.utc)

    # 1. Find ALL sprints for the project (including completed)
    result = await db.execute(
        _select(Sprint).where(
            Sprint.project_id == project_uuid,
            Sprint.deleted_at.is_(None),
        )
    )
    sprints_to_clear: list = list(result.scalars().all())

    if not sprints_to_clear:
        return {"cleared_sprints": 0, "unassigned_stories": 0}

    sprint_ids = [s.id for s in sprints_to_clear]

    # 2. Unassign all stories belonging to these sprints
    unassign_result = await db.execute(
        _update(UserStory)
        .where(
            UserStory.current_sprint_id.in_(sprint_ids),
            UserStory.deleted_at.is_(None),
        )
        .values(current_sprint_id=None, updated_at=now)
    )
    unassigned_count: int = unassign_result.rowcount  # type: ignore[assignment]

    # 3. Soft-delete the sprint rows
    for sprint in sprints_to_clear:
        sprint.deleted_at = now  # type: ignore[assignment]

    await db.commit()

    return {
        "cleared_sprints": len(sprints_to_clear),
        "unassigned_stories": unassigned_count,
    }


class AddStoryRequest(BaseModel):
    story_id: str = Field(alias="storyId")

    model_config = {"populate_by_name": True}


@router.post(
    "/{sprint_id}/stories",
    status_code=status.HTTP_200_OK,
    summary="Assign a story to a sprint",
)
async def add_story_to_sprint(
    sprint_id: str,
    payload: AddStoryRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a backlog story to a sprint (drag-and-drop or manual)."""
    import uuid as _uuid
    from sqlalchemy import update as _update
    from app.models.user_story import UserStory

    # Validate sprint exists
    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")

    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))

    try:
        story_uuid = _uuid.UUID(payload.story_id)
        sprint_uuid = _uuid.UUID(sprint_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format.")

    story = await db.get(UserStory, story_uuid)
    if not story:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")

    await db.execute(
        _update(UserStory)
        .where(UserStory.id == story_uuid)
        .values(current_sprint_id=sprint_uuid)
    )
    await db.commit()
    return {"sprint_id": sprint_id, "story_id": payload.story_id, "assigned": True}


@router.delete(
    "/{sprint_id}/stories/{story_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove a story from a sprint (back to backlog)",
)
async def remove_story_from_sprint(
    sprint_id: str,
    story_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a story assignment from a sprint — story returns to backlog."""
    import uuid as _uuid
    from sqlalchemy import update as _update
    from app.models.user_story import UserStory

    svc = SprintService(db)
    sprint = await svc.get_by_id(sprint_id)
    if not sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")

    await verify_project_access(db, project_id=str(sprint.project_id), user_id=str(current_user.id))

    try:
        story_uuid = _uuid.UUID(story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid story ID.")

    story = await db.get(UserStory, story_uuid)
    if not story:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")

    await db.execute(
        _update(UserStory)
        .where(UserStory.id == story_uuid)
        .values(current_sprint_id=None)
    )
    await db.commit()
    return {"sprint_id": sprint_id, "story_id": story_id, "removed": True}
