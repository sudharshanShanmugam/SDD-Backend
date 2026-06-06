"""
Project management API routes.
Project CRUD, workflow stage management.
"""
import logging
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)
router = APIRouter()


class WorkflowStage(str, Enum):
    DISCOVERY = "discovery"
    REQUIREMENTS = "requirements"
    DESIGN = "design"
    DEVELOPMENT = "development"
    QA = "qa"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    workspace_id: str
    description: str | None = None
    key: str | None = Field(default=None, pattern=r"^[A-Z]{2,10}$", max_length=10)
    workflow_stage: WorkflowStage = WorkflowStage.DISCOVERY
    start_date: str | None = None
    target_date: str | None = None
    settings: dict | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    workflow_stage: WorkflowStage | None = None
    start_date: str | None = None
    target_date: str | None = None
    settings: dict | None = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    key: str
    description: Optional[str] = None
    organization_id: Optional[UUID] = None
    workspace_id: UUID
    workflow_stage: str
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    epic_count: Optional[int] = None
    story_count: Optional[int] = None
    task_count: Optional[int] = None
    open_sprint_id: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowStageUpdateRequest(BaseModel):
    stage: WorkflowStage
    reason: str | None = None


class ProjectMemberRequest(BaseModel):
    user_id: str
    role: str = Field(default="developer", pattern="^(owner|manager|developer|viewer)$")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create project",
)
async def create_project(
    payload: ProjectCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project within a workspace."""
    svc = ProjectService(db)
    return await svc.create_project(
        name=payload.name,
        workspace_id=payload.workspace_id,
        description=payload.description,
        key=payload.key,
        workflow_stage=payload.workflow_stage.value,
        start_date=payload.start_date,
        target_date=payload.target_date,
        settings=payload.settings or {},
        created_by=str(current_user.id),
    )


@router.get(
    "",
    summary="List projects",
)
async def list_projects(
    workspace_id: str | None = Query(default=None),
    workflow_stage: WorkflowStage | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List projects accessible to the current user."""
    svc = ProjectService(db)
    return await svc.list_projects(
        user_id=str(current_user.id),
        workspace_id=workspace_id,
        workflow_stage=workflow_stage.value if workflow_stage else None,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project details",
)
async def get_project(
    project_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    project = await svc.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    await svc.assert_access(project_id=project_id, user_id=str(current_user.id))
    return project


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
)
async def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    await svc.assert_manager(project_id=project_id, user_id=str(current_user.id))
    return await svc.update_project(
        project_id=project_id,
        data=payload.model_dump(exclude_none=True),
    )


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project",
)
async def delete_project(
    project_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    await svc.assert_owner(project_id=project_id, user_id=str(current_user.id))
    await svc.delete_project(project_id=project_id)


@router.patch(
    "/{project_id}/workflow-stage",
    response_model=ProjectResponse,
    summary="Advance workflow stage",
)
async def update_workflow_stage(
    project_id: str,
    payload: WorkflowStageUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition a project to a new workflow stage."""
    svc = ProjectService(db)
    await svc.assert_manager(project_id=project_id, user_id=str(current_user.id))
    updated = await svc.transition_stage(
        project_id=project_id,
        new_stage=payload.stage.value,
        changed_by=str(current_user.id),
        reason=payload.reason,
    )
    return updated


@router.get(
    "/{project_id}/members",
    summary="List project members",
)
async def list_project_members(
    project_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    await svc.assert_access(project_id=project_id, user_id=str(current_user.id))
    return await svc.list_members(project_id=project_id)


@router.get(
    "/{project_id}/workspace-members",
    summary="List workspace members available for this project (used for assignee picker)",
)
async def list_project_workspace_members(
    project_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns all members of the workspace this project belongs to."""
    from sqlalchemy import select as _select
    from app.models.project import Project
    from app.models.workspace import WorkspaceMember
    from app.models.user import User

    svc = ProjectService(db)
    await svc.assert_access(project_id=project_id, user_id=str(current_user.id))

    try:
        proj_uuid = uuid.UUID(project_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid project_id")

    project_row = (await db.execute(_select(Project).where(Project.id == proj_uuid))).scalar_one_or_none()
    if not project_row or not project_row.workspace_id:
        return []

    result = await db.execute(
        _select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == project_row.workspace_id)
        .where(User.is_active == True)
    )
    return [
        {
            "id": str(u.id),
            "userId": str(u.id),
            "user": {
                "id": str(u.id),
                "displayName": u.full_name,
                "email": u.email,
                "avatar": getattr(u, "avatar_url", None),
            },
            "role": m.role,
        }
        for m, u in result.all()
    ]


@router.post(
    "/{project_id}/members",
    status_code=status.HTTP_201_CREATED,
    summary="Add member to project",
)
async def add_project_member(
    project_id: str,
    payload: ProjectMemberRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    await svc.assert_manager(project_id=project_id, user_id=str(current_user.id))
    return await svc.add_member(
        project_id=project_id,
        user_id=payload.user_id,
        role=payload.role,
    )


@router.put(
    "/{project_id}/members/{user_id}",
    summary="Update project member role",
)
async def update_project_member(
    project_id: str,
    user_id: str,
    payload: ProjectMemberRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    await svc.assert_manager(project_id=project_id, user_id=str(current_user.id))
    result = await svc.update_member_role(project_id=project_id, user_id=user_id, role=payload.role)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return result


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member from project",
)
async def remove_project_member(
    project_id: str,
    user_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ProjectService(db)
    await svc.assert_manager(project_id=project_id, user_id=str(current_user.id))
    removed = await svc.remove_member(project_id=project_id, user_id=user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")


@router.get(
    "/{project_id}/stats",
    summary="Get project statistics",
)
async def get_project_stats(
    project_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get project progress stats: epics, stories, tasks, sprints."""
    svc = ProjectService(db)
    await svc.assert_access(project_id=project_id, user_id=str(current_user.id))
    return await svc.get_stats(project_id=project_id)
