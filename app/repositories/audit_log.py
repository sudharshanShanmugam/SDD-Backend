"""AuditLog repository – append-only writes, query helpers."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.core.constants import AuditAction
from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self, db) -> None:
        super().__init__(db, AuditLog)

    async def log(
        self,
        action: AuditAction,
        resource_type: str,
        resource_id: Optional[str] = None,
        resource_name: Optional[str] = None,
        user_id: Optional[UUID] = None,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        org_id: Optional[UUID] = None,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
        changed_fields: Optional[list] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> AuditLog:
        """Write a single immutable audit record."""
        import uuid

        record = AuditLog(
            id=uuid.uuid4(),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            user_id=user_id,
            user_email=user_email,
            user_role=user_role,
            organization_id=org_id,
            old_values=old_values,
            new_values=new_values,
            changed_fields=changed_fields,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            description=description,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def list_for_resource(
        self,
        resource_type: str,
        resource_id: str,
        org_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLog], int]:
        from sqlalchemy import desc

        stmt = (
            select(AuditLog)
            .where(AuditLog.resource_type == resource_type)
            .where(AuditLog.resource_id == resource_id)
        )
        if org_id:
            stmt = stmt.where(AuditLog.organization_id == org_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def list_for_user(
        self,
        user_id: UUID,
        org_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 50,
        action: Optional[AuditAction] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> tuple[list[AuditLog], int]:
        from sqlalchemy import desc

        stmt = select(AuditLog).where(AuditLog.user_id == user_id)
        if org_id:
            stmt = stmt.where(AuditLog.organization_id == org_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if from_date:
            stmt = stmt.where(AuditLog.created_at >= from_date)
        if to_date:
            stmt = stmt.where(AuditLog.created_at <= to_date)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total
