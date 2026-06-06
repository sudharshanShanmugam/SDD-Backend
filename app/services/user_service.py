"""
User Service.
User business logic: CRUD, preferences, role management.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default preferences stored in the JSONB preferences column on User
_DEFAULT_PREFERENCES = {
    "theme": "system",
    "notifications_email": True,
    "notifications_push": True,
    "notifications_in_app": True,
    "ai_suggestions_enabled": True,
    "default_view": "board",
}


class UserService:
    """Handles user management business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(
        self,
        email: str,
        password: str,
        full_name: str,
        organization_name: str | None = None,
        role: str = "member",
    ):
        """Create a new user, optionally with a personal organization."""
        from app.models.user import User
        from app.services.auth_service import AuthService

        auth_svc = AuthService(self.db)
        hashed = auth_svc.hash_password(password)

        user = User(
            id=uuid.uuid4(),
            email=email.lower().strip(),
            hashed_password=hashed,
            full_name=full_name,
            role=role,
            is_active=True,
            is_verified=False,
            # Store preferences in the User.preferences JSONB column
            preferences=dict(_DEFAULT_PREFERENCES),
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        # Create personal organization if requested
        if organization_name:
            from app.services.organization_service import OrganizationService
            org_svc = OrganizationService(self.db)
            await org_svc.create_organization(
                name=organization_name,
                owner_id=str(user.id),
            )

        logger.info("User created: %s (%s)", user.email, user.id)
        return user

    async def get_by_id(self, user_id: str):
        from app.models.user import User
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str):
        from app.models.user import User
        result = await self.db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        is_active: bool | None = None,
        role: str | None = None,
    ) -> dict:
        from app.models.user import User

        query = select(User)
        if search:
            query = query.where(
                User.full_name.ilike(f"%{search}%") | User.email.ilike(f"%{search}%")
            )
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        if role:
            query = query.where(User.role == role)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = query.order_by(User.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        items = (await self.db.execute(query)).scalars().all()

        pages = (total + page_size - 1) // page_size
        return {
            "items": [_serialize_user(u) for u in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    async def update_user(self, user_id: str, data: dict):
        from app.models.user import User
        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(update(User).where(User.id == user_id).values(**data))
        await self.db.commit()
        return await self.get_by_id(user_id)

    async def update_role(self, user_id: str, role: str):
        return await self.update_user(user_id, {"role": role})

    async def deactivate_user(self, user_id: str) -> bool:
        user = await self.get_by_id(user_id)
        if not user:
            return False
        await self.update_user(user_id, {"is_active": False})
        return True

    async def delete_user(self, user_id: str) -> bool:
        from app.models.user import User
        from sqlalchemy import delete as sql_delete
        user = await self.get_by_id(user_id)
        if not user:
            return False
        await self.db.execute(sql_delete(User).where(User.id == user_id))
        await self.db.commit()
        return True

    async def get_preferences(self, user_id: str) -> dict:
        """Return the preferences dict stored in User.preferences JSONB column."""
        user = await self.get_by_id(user_id)
        if not user:
            return dict(_DEFAULT_PREFERENCES)
        prefs = user.preferences or {}
        # Merge with defaults so any new keys are present
        merged = {**_DEFAULT_PREFERENCES, **prefs}
        return merged

    async def update_preferences(self, user_id: str, data: dict) -> dict:
        """Merge new preference values into User.preferences JSONB."""
        from app.models.user import User
        # Get current prefs, merge, write back
        current = await self.get_preferences(user_id)
        merged = {**current, **data}
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(preferences=merged, updated_at=datetime.now(tz=timezone.utc))
        )
        await self.db.commit()
        return merged


def _serialize_user(u) -> dict:
    """Serialize a User ORM object to a frontend-friendly dict."""
    role_raw = u.role
    if hasattr(role_raw, "value"):
        role_raw = role_raw.value
    return {
        "id": str(u.id),
        "email": u.email,
        "full_name": u.full_name,
        "is_active": u.is_active,
        "is_verified": u.is_verified,
        "role": str(role_raw) if role_raw else "member",
        "avatar_url": u.avatar_url,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "updated_at": u.updated_at.isoformat() if u.updated_at else None,
    }
