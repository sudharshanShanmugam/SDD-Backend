"""Workspace repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import select

from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    def __init__(self, db) -> None:
        super().__init__(db, Workspace)

    async def get_by_slug(self, org_id: UUID, slug: str) -> Optional[Workspace]:
        stmt = (
            select(Workspace)
            .where(Workspace.organization_id == org_id)
            .where(Workspace.slug == slug.lower())
            .where(Workspace.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def slug_exists(
        self, org_id: UUID, slug: str, exclude_id: Optional[UUID] = None
    ) -> bool:
        stmt = (
            select(Workspace)
            .where(Workspace.organization_id == org_id)
            .where(Workspace.slug == slug.lower())
            .where(Workspace.deleted_at.is_(None))
        )
        if exclude_id:
            stmt = stmt.where(Workspace.id != exclude_id)
        result = await self.db.execute(stmt)
        return result.scalars().first() is not None

    async def list_by_org(
        self,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        is_active: Optional[bool] = None,
    ) -> tuple[list[Workspace], int]:
        from sqlalchemy import func, desc

        stmt = (
            select(Workspace)
            .where(Workspace.organization_id == org_id)
            .where(Workspace.deleted_at.is_(None))
        )
        if is_active is not None:
            stmt = stmt.where(Workspace.is_active == is_active)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(desc(Workspace.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def get_default(self, org_id: UUID) -> Optional[Workspace]:
        stmt = (
            select(Workspace)
            .where(Workspace.organization_id == org_id)
            .where(Workspace.is_default == True)
            .where(Workspace.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_member(self, ws_id: UUID, user_id: UUID) -> Optional[WorkspaceMember]:
        stmt = (
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == ws_id)
            .where(WorkspaceMember.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()
