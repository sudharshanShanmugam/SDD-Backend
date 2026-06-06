"""
Notification Service.
In-app notifications, push, email, preferences.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_notification(n) -> dict:
    """Serialize a Notification ORM object."""
    def _str(v):
        return str(v) if v is not None else None

    notif_type = n.notification_type
    if hasattr(notif_type, "value"):
        notif_type = notif_type.value

    return {
        "id": _str(n.id),
        "user_id": _str(n.user_id),
        "title": n.title or "",
        "message": n.body or "",
        "notification_type": str(notif_type) if notif_type else "general",
        "entity_type": n.resource_type,
        "entity_id": n.resource_id,
        "action_url": n.action_url,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_notification(
        self,
        user_id: str,
        title: str,
        message: str,
        notification_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        action_url: str | None = None,
        metadata: dict | None = None,
    ):
        from app.models.notification import Notification

        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            user_uuid = user_id

        notif = Notification(
            id=uuid.uuid4(),
            user_id=user_uuid,
            title=title,
            body=message,                     # model uses 'body' not 'message'
            notification_type=notification_type,
            resource_type=entity_type,        # model uses 'resource_type' not 'entity_type'
            resource_id=entity_id,            # model uses 'resource_id' not 'entity_id'
            action_url=action_url,
            is_read=False,
        )
        self.db.add(notif)
        await self.db.commit()
        await self.db.refresh(notif)

        # Push via WebSocket (non-critical)
        await self._push_realtime(user_id, notif)
        return notif

    async def list_notifications(
        self,
        user_id: str,
        is_read: bool | None,
        notification_type: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.notification import Notification

        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            user_uuid = user_id

        query = select(Notification).where(Notification.user_id == user_uuid)
        if is_read is not None:
            query = query.where(Notification.is_read == is_read)
        if notification_type:
            query = query.where(Notification.notification_type == notification_type)

        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(Notification.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_notification(n) for n in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_unread_count(self, user_id: str) -> int:
        from app.models.notification import Notification
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            user_uuid = user_id
        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_uuid,
                Notification.is_read == False,
            )
        )
        return result.scalar_one() or 0

    async def mark_as_read(self, notification_id: str, user_id: str) -> None:
        from app.models.notification import Notification
        try:
            notif_uuid = uuid.UUID(notification_id)
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            return
        await self.db.execute(
            update(Notification)
            .where(Notification.id == notif_uuid, Notification.user_id == user_uuid)
            .values(is_read=True, read_at=datetime.now(tz=timezone.utc).isoformat())
        )
        await self.db.commit()

    async def mark_all_read(self, user_id: str) -> None:
        from app.models.notification import Notification
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            user_uuid = user_id
        await self.db.execute(
            update(Notification)
            .where(Notification.user_id == user_uuid, Notification.is_read == False)
            .values(is_read=True, read_at=datetime.now(tz=timezone.utc).isoformat())
        )
        await self.db.commit()

    async def delete_notification(self, notification_id: str, user_id: str) -> None:
        from app.models.notification import Notification
        from sqlalchemy import delete as sql_delete
        try:
            notif_uuid = uuid.UUID(notification_id)
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            return
        await self.db.execute(
            sql_delete(Notification).where(
                Notification.id == notif_uuid,
                Notification.user_id == user_uuid,
            )
        )
        await self.db.commit()

    async def clear_all(self, user_id: str) -> None:
        from app.models.notification import Notification
        from sqlalchemy import delete as sql_delete
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            user_uuid = user_id
        await self.db.execute(
            sql_delete(Notification).where(Notification.user_id == user_uuid)
        )
        await self.db.commit()

    async def get_preferences(self, user_id: str) -> dict:
        """Return notification preferences from User.preferences JSONB column."""
        from app.models.user import User
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            user_uuid = user_id

        result = await self.db.execute(
            select(User.preferences).where(User.id == user_uuid)
        )
        row = result.scalar_one_or_none()
        prefs = row or {}
        notif_prefs = prefs.get("notifications", {})
        return {
            "user_id": user_id,
            "email_enabled": notif_prefs.get("email_enabled", True),
            "push_enabled": notif_prefs.get("push_enabled", True),
            "in_app_enabled": notif_prefs.get("in_app_enabled", True),
            "digest_enabled": notif_prefs.get("digest_enabled", False),
            "digest_frequency": notif_prefs.get("digest_frequency", "daily"),
            "event_types": notif_prefs.get("event_types", {}),
        }

    async def update_preferences(self, user_id: str, data: dict) -> dict:
        """Merge notification preferences into User.preferences JSONB column."""
        from app.models.user import User
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy import cast as sa_cast
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            user_uuid = user_id

        # Load current prefs
        result = await self.db.execute(
            select(User.preferences).where(User.id == user_uuid)
        )
        row = result.scalar_one_or_none()
        current_prefs = dict(row or {})
        current_notif = dict(current_prefs.get("notifications", {}))
        current_notif.update(data)
        current_prefs["notifications"] = current_notif

        await self.db.execute(
            update(User)
            .where(User.id == user_uuid)
            .values(preferences=current_prefs)
        )
        await self.db.commit()
        return await self.get_preferences(user_id)

    async def _push_realtime(self, user_id: str, notification) -> None:
        """Push notification via WebSocket to connected clients."""
        try:
            from app.websockets.manager import ws_manager
            await ws_manager.send_to_user(
                user_id=user_id,
                event="notification.new",
                data={
                    "id": str(notification.id),
                    "title": notification.title,
                    "message": notification.body or "",
                    "type": str(notification.notification_type),
                    "created_at": notification.created_at.isoformat() if notification.created_at else None,
                },
            )
        except Exception as exc:
            logger.debug("WebSocket push failed (non-critical): %s", exc)
