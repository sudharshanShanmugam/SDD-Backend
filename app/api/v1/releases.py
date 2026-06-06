"""
Release management API routes.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_project_access
from app.services.release_service import ReleaseService, _serialize_release

logger = logging.getLogger(__name__)
router = APIRouter()


class ReleaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=50)
    project_id: str
    description: str | None = None
    sprint_ids: list[str] | None = None
    target_date: str | None = None
    release_type: str = Field(default="minor", pattern="^(major|minor|patch|hotfix)$")


class ReleaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    target_date: str | None = None
    status: str | None = None
    release_notes: str | None = None


class ReleaseResponse(BaseModel):
    id: str
    name: str
    version: str
    project_id: str
    description: str | None
    status: str
    release_type: str
    target_date: str | None
    released_at: str | None
    sprint_count: int
    story_count: int
    created_by: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create release",
)
async def create_release(
    payload: ReleaseCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(db, project_id=payload.project_id, user_id=str(current_user.id))
    svc = ReleaseService(db)
    return await svc.create_release(
        **payload.model_dump(),
        created_by=str(current_user.id),
    )


@router.get(
    "",
    summary="List releases",
)
async def list_releases(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    release_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if project_id:
        await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    svc = ReleaseService(db)
    return await svc.list_releases(
        user_id=str(current_user.id),
        project_id=project_id,
        status=status,
        release_type=release_type,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{release_id}",
    summary="Get release details",
)
async def get_release(
    release_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReleaseService(db)
    release = await svc.get_by_id(release_id)
    if not release:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")
    await verify_project_access(db, project_id=str(release.project_id), user_id=str(current_user.id))
    return _serialize_release(release)


@router.patch(
    "/{release_id}",
    summary="Update release",
)
async def update_release(
    release_id: str,
    payload: ReleaseUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReleaseService(db)
    release = await svc.get_by_id(release_id)
    if not release:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")
    await verify_project_access(db, project_id=str(release.project_id), user_id=str(current_user.id))
    return await svc.update_release(
        release_id=release_id,
        data=payload.model_dump(exclude_none=True),
    )


@router.delete(
    "/{release_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete release",
)
async def delete_release(
    release_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ReleaseService(db)
    release = await svc.get_by_id(release_id)
    if not release:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")
    await verify_project_access(db, project_id=str(release.project_id), user_id=str(current_user.id))
    release_status = release.status
    if hasattr(release_status, "value"):
        release_status = release_status.value
    if release_status == "released":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a published release.",
        )
    await svc.delete_release(release_id=release_id)


@router.post(
    "/{release_id}/publish",
    summary="Publish release",
)
async def publish_release(
    release_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a release as published and record the release date."""
    svc = ReleaseService(db)
    release = await svc.get_by_id(release_id)
    if not release:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")
    await verify_project_access(db, project_id=str(release.project_id), user_id=str(current_user.id))
    return await svc.publish_release(
        release_id=release_id,
        published_by=str(current_user.id),
    )


@router.get(
    "/{release_id}/changelog",
    summary="Get release changelog",
)
async def get_changelog(
    release_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the grouped changelog for the release: features, bugfixes, improvements."""
    svc = ReleaseService(db)
    release = await svc.get_by_id(release_id)
    if not release:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")
    await verify_project_access(db, project_id=str(release.project_id), user_id=str(current_user.id))
    return await svc.get_changelog(release_id=release_id)
