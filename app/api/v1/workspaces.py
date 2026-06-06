"""
Workspace management API routes.
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)
router = APIRouter()


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    organization_id: str
    description: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = None
    settings: dict | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    settings: dict | None = None


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None = None
    organization_id: UUID
    color: str | None = None
    icon: str | None = None
    is_default: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create workspace",
)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkspaceService(db)
    return await svc.create_workspace(
        name=payload.name,
        org_id=payload.organization_id,
        description=payload.description,
        color=payload.color,
        icon=payload.icon,
        settings=payload.settings or {},
        created_by=str(current_user.id),
    )


@router.get(
    "",
    summary="List workspaces",
)
async def list_workspaces(
    organization_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkspaceService(db)
    return await svc.list_workspaces(
        user_id=str(current_user.id),
        org_id=organization_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Get workspace details",
)
async def get_workspace(
    workspace_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkspaceService(db)
    ws = await svc.get_by_id(workspace_id)
    if not ws:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    await svc.assert_access(workspace_id=workspace_id, user_id=str(current_user.id))
    return ws


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Update workspace",
)
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkspaceService(db)
    await svc.assert_admin(workspace_id=workspace_id, user_id=str(current_user.id))
    return await svc.update_workspace(
        workspace_id=workspace_id,
        data=payload.model_dump(exclude_none=True),
    )


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete workspace",
)
async def delete_workspace(
    workspace_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkspaceService(db)
    await svc.assert_admin(workspace_id=workspace_id, user_id=str(current_user.id))
    await svc.delete_workspace(workspace_id=workspace_id)


@router.get(
    "/{workspace_id}/members",
    summary="List workspace members",
)
async def list_workspace_members(
    workspace_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkspaceService(db)
    await svc.assert_access(workspace_id=workspace_id, user_id=str(current_user.id))
    return await svc.list_members(workspace_id=workspace_id)


@router.post(
    "/{workspace_id}/members",
    status_code=status.HTTP_201_CREATED,
    summary="Add member to workspace",
)
async def add_workspace_member(
    workspace_id: str,
    user_id: str,
    role: str = "member",
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkspaceService(db)
    await svc.assert_admin(workspace_id=workspace_id, user_id=str(current_user.id))
    return await svc.add_member(workspace_id=workspace_id, user_id=user_id, role=role)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member from workspace",
)
async def remove_workspace_member(
    workspace_id: str,
    user_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkspaceService(db)
    await svc.assert_admin(workspace_id=workspace_id, user_id=str(current_user.id))
    await svc.remove_member(workspace_id=workspace_id, user_id=user_id)
