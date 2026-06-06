"""Organization repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.models.organization import Organization, OrganizationMember
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization]):
    def __init__(self, db) -> None:
        super().__init__(db, Organization)

    async def get_by_slug(self, slug: str) -> Optional[Organization]:
        stmt = (
            select(Organization)
            .where(Organization.slug == slug.lower())
            .where(Organization.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def slug_exists(self, slug: str, exclude_id: Optional[UUID] = None) -> bool:
        stmt = (
            select(Organization)
            .where(Organization.slug == slug.lower())
            .where(Organization.deleted_at.is_(None))
        )
        if exclude_id:
            stmt = stmt.where(Organization.id != exclude_id)
        result = await self.db.execute(stmt)
        return result.scalars().first() is not None

    async def get_member(self, org_id: UUID, user_id: UUID) -> Optional[OrganizationMember]:
        stmt = (
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == org_id)
            .where(OrganizationMember.user_id == user_id)
            .where(OrganizationMember.is_active == True)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def count_members(self, org_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(OrganizationMember)
            .where(OrganizationMember.organization_id == org_id)
            .where(OrganizationMember.is_active == True)
        )
        return (await self.db.execute(stmt)).scalar_one()

    async def add_member(
        self,
        org_id: UUID,
        user_id: UUID,
        role: str,
        invited_by: Optional[UUID] = None,
    ) -> OrganizationMember:
        import uuid

        member = OrganizationMember(
            id=uuid.uuid4(),
            organization_id=org_id,
            user_id=user_id,
            role=role,
            is_active=True,
            invited_by=invited_by,
        )
        self.db.add(member)
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def remove_member(self, org_id: UUID, user_id: UUID) -> bool:
        member = await self.get_member(org_id, user_id)
        if member is None:
            return False
        member.is_active = False
        await self.db.flush()
        return True


class OrganizationMemberRepository(BaseRepository[OrganizationMember]):
    def __init__(self, db) -> None:
        super().__init__(db, OrganizationMember)
