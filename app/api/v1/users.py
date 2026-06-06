"""
User management API routes.
CRUD operations, profile management, preferences.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_admin
from app.services.user_service import UserService, _serialize_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = None
    timezone: str | None = None
    locale: str | None = None


class UserPreferencesUpdate(BaseModel):
    theme: str | None = None
    notifications_email: bool | None = None
    notifications_push: bool | None = None
    notifications_in_app: bool | None = None
    digest_frequency: str | None = None
    ai_suggestions_enabled: bool | None = None
    default_view: str | None = None


class RoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(admin|member|viewer)$")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List users (admin only)",
)
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users with pagination and optional search. Admin only."""
    svc = UserService(db)
    return await svc.list_users(
        page=page,
        page_size=page_size,
        search=search,
        is_active=is_active,
    )


@router.get(
    "/me",
    summary="Get current user profile",
)
async def get_my_profile(current_user=Depends(get_current_user)):
    """Return the current user's full profile."""
    return _serialize_user(current_user)


@router.patch(
    "/me",
    summary="Update current user profile",
)
async def update_my_profile(
    payload: UserUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile fields."""
    svc = UserService(db)
    updated = await svc.update_user(
        user_id=str(current_user.id),
        data=payload.model_dump(exclude_none=True),
    )
    return _serialize_user(updated) if updated else None


@router.get(
    "/me/preferences",
    summary="Get current user preferences",
)
async def get_my_preferences(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the current user's UI and notification preferences."""
    svc = UserService(db)
    return await svc.get_preferences(user_id=str(current_user.id))


@router.patch(
    "/me/preferences",
    summary="Update current user preferences",
)
async def update_my_preferences(
    payload: UserPreferencesUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's preferences."""
    svc = UserService(db)
    return await svc.update_preferences(
        user_id=str(current_user.id),
        data=payload.model_dump(exclude_none=True),
    )


@router.get(
    "/{user_id}",
    summary="Get user by ID",
)
async def get_user(
    user_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific user's public profile."""
    svc = UserService(db)
    user = await svc.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return _serialize_user(user)


@router.patch(
    "/{user_id}",
    summary="Update user (admin only)",
)
async def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update any user's profile. Admin only."""
    svc = UserService(db)
    updated = await svc.update_user(
        user_id=user_id,
        data=payload.model_dump(exclude_none=True),
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return _serialize_user(updated)


@router.patch(
    "/{user_id}/role",
    summary="Update user role (admin only)",
)
async def update_user_role(
    user_id: str,
    payload: RoleUpdateRequest,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change a user's system role. Admin only."""
    svc = UserService(db)
    updated = await svc.update_role(user_id=user_id, role=payload.role)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return _serialize_user(updated)


@router.patch(
    "/{user_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate user (admin only)",
)
async def deactivate_user(
    user_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user account. Admin only."""
    if str(current_user.id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account.",
        )
    svc = UserService(db)
    success = await svc.deactivate_user(user_id=user_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user (admin only)",
)
async def delete_user(
    user_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a user account. Admin only."""
    if str(current_user.id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account.",
        )
    svc = UserService(db)
    success = await svc.delete_user(user_id=user_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
