"""Requirement repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.models.requirement import Requirement
from app.repositories.base import BaseRepository


class RequirementRepository(BaseRepository[Requirement]):
    def __init__(self, db) -> None:
        super().__init__(db, Requirement)

    async def get_next_number(self, project_id: UUID, org_id: UUID) -> str:
        stmt = (
            select(func.count())
            .select_from(Requirement)
            .where(Requirement.project_id == project_id)
            .where(Requirement.organization_id == org_id)
        )
        count = (await self.db.execute(stmt)).scalar_one()
        return f"REQ-{count + 1:04d}"

    async def list_by_project(
        self,
        project_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        req_type: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        source_document_id: Optional[UUID] = None,
    ) -> tuple[list[Requirement], int]:
        from sqlalchemy import desc, or_

        stmt = (
            select(Requirement)
            .where(Requirement.project_id == project_id)
            .where(Requirement.organization_id == org_id)
            .where(Requirement.deleted_at.is_(None))
        )
        if req_type:
            stmt = stmt.where(Requirement.requirement_type == req_type)
        if priority:
            stmt = stmt.where(Requirement.priority == priority)
        if status:
            stmt = stmt.where(Requirement.status == status)
        if source_document_id:
            stmt = stmt.where(Requirement.source_document_id == source_document_id)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Requirement.title.ilike(pattern),
                    Requirement.description.ilike(pattern),
                    Requirement.req_number.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(desc(Requirement.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def bulk_create_from_ai(
        self, requirements_data: list[dict], project_id: UUID, org_id: UUID
    ) -> list[Requirement]:
        """Create multiple requirements from AI extraction results."""
        objs = []
        for data in requirements_data:
            req_number = await self.get_next_number(project_id, org_id)
            req = Requirement(
                project_id=project_id,
                organization_id=org_id,
                req_number=req_number,
                **data,
            )
            self.db.add(req)
            objs.append(req)
        await self.db.flush()
        return objs
