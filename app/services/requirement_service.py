"""
Requirement Service.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RequirementService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_requirement(self, **kwargs) -> object:
        from app.models.requirement import Requirement
        from app.models.project import Project
        from app.core.constants import ApprovalStatus
        from sqlalchemy import func

        # ── Pull out fields that need renaming or special handling ────────
        project_id_str: str = kwargs.pop("project_id", None) or ""
        document_id_str: str | None = kwargs.pop("document_id", None)
        req_type: str = kwargs.pop("type", "functional")
        raw_ac = kwargs.pop("acceptance_criteria", None)
        acceptance_criteria: str = (
            "\n".join(raw_ac) if isinstance(raw_ac, list) else (raw_ac or "")
        )
        kwargs.pop("source", None)          # not a column; discard
        created_by_str = kwargs.pop("created_by", None)

        if not project_id_str:
            raise ValueError("project_id is required")

        project_uuid = uuid.UUID(project_id_str)

        # ── Resolve organization_id from project ───────────────────────────
        row = await self.db.execute(
            select(Project).where(Project.id == project_uuid)
        )
        project = row.scalar_one_or_none()
        org_id = (
            project.organization_id
            if project
            else uuid.UUID("00000000-0000-0000-0000-000000000020")
        )

        # ── Auto-generate REQ number ───────────────────────────────────────
        count_row = await self.db.execute(
            select(func.count()).select_from(Requirement).where(
                Requirement.project_id == project_uuid
            )
        )
        req_number = f"REQ-{count_row.scalar_one() + 1:03d}"

        now = datetime.now(tz=timezone.utc)
        req = Requirement(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_uuid,
            source_document_id=uuid.UUID(document_id_str) if document_id_str else None,
            req_number=req_number,
            requirement_type=req_type,
            acceptance_criteria=acceptance_criteria,
            status=ApprovalStatus.PENDING.value,
            is_ai_generated=False,
            created_by=uuid.UUID(str(created_by_str)) if created_by_str else None,
            tags=kwargs.pop("tags", None) or [],
            created_at=now,
            updated_at=now,
            **kwargs,          # title, description, priority
        )
        self.db.add(req)
        await self.db.commit()
        await self.db.refresh(req)
        return req

    async def get_by_id(self, req_id: str):
        from app.models.requirement import Requirement
        result = await self.db.execute(
            select(Requirement).where(
                Requirement.id == req_id,
                Requirement.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_requirements(
        self,
        user_id: str,
        project_id: str | None,
        req_type: str | None,
        priority: str | None,
        status: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.requirement import Requirement

        query = select(Requirement).where(Requirement.deleted_at.is_(None))
        if project_id:
            query = query.where(Requirement.project_id == project_id)
        if req_type:
            query = query.where(Requirement.requirement_type == req_type)
        if priority:
            query = query.where(Requirement.priority == priority)
        if status:
            query = query.where(Requirement.status == status)
        if search:
            query = query.where(Requirement.title.ilike(f"%{search}%"))

        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(Requirement.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def update_requirement(self, req_id: str, data: dict, updated_by: str):
        from app.models.requirement import Requirement
        data["updated_at"] = datetime.now(tz=timezone.utc)
        # Cast to uuid.UUID so asyncpg doesn't silently skip the row due to type mismatch
        await self.db.execute(
            update(Requirement)
            .where(Requirement.id == uuid.UUID(req_id))
            .values(**data)
        )
        await self.db.commit()
        # expire_all forces SQLAlchemy to discard any cached ORM object
        # and issue a fresh SELECT on the next access
        self.db.expire_all()
        return await self.get_by_id(req_id)

    async def delete_requirement(self, req_id: str) -> None:
        from app.models.requirement import Requirement
        from sqlalchemy import delete as sql_delete
        await self.db.execute(sql_delete(Requirement).where(Requirement.id == req_id))
        await self.db.commit()

    async def bulk_create(self, items: list[dict]) -> list:
        """Bulk create requirements with proper field mapping."""
        created = []
        for item in items:
            try:
                req = await self.create_requirement(**item)
                created.append(req)
            except Exception as exc:
                logger.warning("Bulk create skipped one requirement: %s", exc)
        return created
