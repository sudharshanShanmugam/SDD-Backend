"""User repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db) -> None:
        super().__init__(db, User)

    async def get_by_email(self, email: str, include_deleted: bool = False) -> Optional[User]:
        """Fetch a user by email address."""
        stmt = select(User).where(User.email == email.lower().strip())
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_by_email_and_org(
        self, email: str, org_id: UUID
    ) -> Optional[User]:
        stmt = (
            select(User)
            .where(User.email == email.lower().strip())
            .where(User.organization_id == org_id)
            .where(User.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_by_org(
        self,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> tuple[list[User], int]:
        from sqlalchemy import func, or_, desc

        stmt = (
            select(User)
            .where(User.organization_id == org_id)
            .where(User.deleted_at.is_(None))
        )
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(User.email.ilike(pattern), User.full_name.ilike(pattern))
            )
        if role:
            stmt = stmt.where(User.role == role)
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)

        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(desc(User.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def update_last_login(
        self, user: User, ip_address: Optional[str] = None
    ) -> User:
        from datetime import datetime, timezone

        user.last_login_at = datetime.now(tz=timezone.utc)
        if ip_address:
            user.last_login_ip = ip_address
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.db.flush()
        return user

    async def increment_failed_login(self, user: User) -> User:
        user.failed_login_attempts += 1
        await self.db.flush()
        return user

    async def email_exists(self, email: str) -> bool:
        stmt = (
            select(User)
            .where(User.email == email.lower().strip())
            .where(User.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalars().first() is not None
