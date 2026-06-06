"""Project repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.models.project import Project, ProjectMember
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, db) -> None:
        super().__init__(db, Project)

    async def get_by_key(self, org_id: UUID, key: str) -> Optional[Project]:
        stmt = (
            select(Project)
            .where(Project.organization_id == org_id)
            .where(Project.key == key.upper())
            .where(Project.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def key_exists(
        self, org_id: UUID, key: str, exclude_id: Optional[UUID] = None
    ) -> bool:
        stmt = (
            select(Project)
            .where(Project.organization_id == org_id)
            .where(Project.key == key.upper())
            .where(Project.deleted_at.is_(None))
        )
        if exclude_id:
            stmt = stmt.where(Project.id != exclude_id)
        result = await self.db.execute(stmt)
        return result.scalars().first() is not None

    async def list_by_workspace(
        self,
        workspace_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        is_active: Optional[bool] = None,
        is_archived: Optional[bool] = None,
        workflow_stage: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Project], int]:
        from sqlalchemy import desc, or_

        stmt = (
            select(Project)
            .where(Project.workspace_id == workspace_id)
            .where(Project.organization_id == org_id)
            .where(Project.deleted_at.is_(None))
        )
        if is_active is not None:
            stmt = stmt.where(Project.is_active == is_active)
        if is_archived is not None:
            stmt = stmt.where(Project.is_archived == is_archived)
        if workflow_stage:
            stmt = stmt.where(Project.workflow_stage == workflow_stage)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(Project.name.ilike(pattern), Project.key.ilike(pattern))
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(desc(Project.updated_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def advance_stage(self, project: Project, next_stage: str) -> Project:
        project.workflow_stage = next_stage
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def get_member(self, project_id: UUID, user_id: UUID) -> Optional[ProjectMember]:
        stmt = (
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .where(ProjectMember.user_id == user_id)
            .where(ProjectMember.is_active == True)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()
