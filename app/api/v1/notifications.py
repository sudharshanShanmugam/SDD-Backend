"""
Notification management API routes.
"""
import logging

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter()


class NotificationPreferencesUpdate(BaseModel):
    email_enabled: bool | None = None
    push_enabled: bool | None = None
    in_app_enabled: bool | None = None
    digest_enabled: bool | None = None
    digest_frequency: str | None = None
    event_types: dict | None = None


@router.get(
    "",
    summary="List notifications for current user",
)
async def list_notifications(
    is_read: bool | None = Query(default=None),
    notification_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = NotificationService(db)
    return await svc.list_notifications(
        user_id=str(current_user.id),
        is_read=is_read,
        notification_type=notification_type,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/unread-count",
    summary="Get unread notification count",
)
async def get_unread_count(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = NotificationService(db)
    count = await svc.get_unread_count(user_id=str(current_user.id))
    return {"unread_count": count}


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark notification as read",
)
async def mark_read(
    notification_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = NotificationService(db)
    await svc.mark_as_read(
        notification_id=notification_id,
        user_id=str(current_user.id),
    )


@router.post(
    "/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark all notifications as read",
)
async def mark_all_read(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = NotificationService(db)
    await svc.mark_all_read(user_id=str(current_user.id))


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete notification",
)
async def delete_notification(
    notification_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = NotificationService(db)
    await svc.delete_notification(
        notification_id=notification_id,
        user_id=str(current_user.id),
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear all notifications",
)
async def clear_all_notifications(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = NotificationService(db)
    await svc.clear_all(user_id=str(current_user.id))


@router.get(
    "/preferences",
    summary="Get notification preferences",
)
async def get_preferences(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = NotificationService(db)
    return await svc.get_preferences(user_id=str(current_user.id))


@router.patch(
    "/preferences",
    summary="Update notification preferences",
)
async def update_preferences(
    payload: NotificationPreferencesUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = NotificationService(db)
    return await svc.update_preferences(
        user_id=str(current_user.id),
        data=payload.model_dump(exclude_none=True),
    )
