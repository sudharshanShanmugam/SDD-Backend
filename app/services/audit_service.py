"""
Audit Service.
Immutable audit log recording and querying.
"""
import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_audit_log(row) -> dict:
    """Serialize an AuditLog ORM object."""
    def _str(v):
        return str(v) if v is not None else None

    action_raw = row.action
    if hasattr(action_raw, "value"):
        action_raw = action_raw.value

    return {
        "id": _str(row.id),
        "entity_type": row.resource_type or "",   # frontend calls it entity_type
        "entity_id": row.resource_id,
        "action": str(action_raw) if action_raw else "",
        "actor_id": _str(row.user_id),
        "organization_id": _str(row.organization_id),
        "ip_address": row.ip_address,
        "description": row.description,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class AuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_id: str,
        metadata: dict | None = None,
        project_id: str | None = None,
        organization_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        """
        Record an immutable audit event. Fire-and-forget; errors are suppressed
        to avoid breaking primary operations.
        """
        try:
            from app.models.audit_log import AuditLog

            actor_uuid = None
            try:
                actor_uuid = uuid.UUID(actor_id) if actor_id else None
            except (ValueError, TypeError):
                pass

            org_uuid = None
            try:
                org_uuid = uuid.UUID(organization_id) if organization_id else None
            except (ValueError, TypeError):
                pass

            entry = AuditLog(
                id=uuid.uuid4(),
                resource_type=entity_type,    # model uses resource_type
                resource_id=str(entity_id) if entity_id else None,  # model uses resource_id (str)
                action=action,
                user_id=actor_uuid,           # model uses user_id
                organization_id=org_uuid,
                ip_address=ip_address,
                description=str(metadata) if metadata else None,
                created_at=datetime.now(tz=timezone.utc),
            )
            self.db.add(entry)
            await self.db.commit()
        except Exception as exc:
            logger.error("Audit log write failed: %s", exc)

    async def query_logs(
        self,
        entity_type: str | None,
        entity_id: str | None,
        actor_id: str | None,
        action: str | None,
        project_id: str | None,
        organization_id: str | None,
        start_date: str | None,
        end_date: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.audit_log import AuditLog

        query = select(AuditLog)
        if entity_type:
            query = query.where(AuditLog.resource_type == entity_type)
        if entity_id:
            query = query.where(AuditLog.resource_id == entity_id)
        if actor_id:
            try:
                query = query.where(AuditLog.user_id == uuid.UUID(actor_id))
            except (ValueError, TypeError):
                pass
        if action:
            query = query.where(AuditLog.action == action)
        if organization_id:
            try:
                query = query.where(AuditLog.organization_id == uuid.UUID(organization_id))
            except (ValueError, TypeError):
                pass
        if start_date:
            query = query.where(AuditLog.created_at >= start_date)
        if end_date:
            query = query.where(AuditLog.created_at <= end_date)

        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(AuditLog.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_audit_log(row) for row in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_entity_trail(
        self,
        entity_type: str,
        entity_id: str,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.audit_log import AuditLog

        query = select(AuditLog).where(
            AuditLog.resource_type == entity_type,
            AuditLog.resource_id == entity_id,
        )
        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(AuditLog.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_audit_log(row) for row in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def export_csv(
        self,
        start_date: str | None,
        end_date: str | None,
        organization_id: str | None,
    ) -> AsyncGenerator[str, None]:
        """Stream audit logs as CSV."""
        from app.models.audit_log import AuditLog

        query = select(AuditLog)
        if start_date:
            query = query.where(AuditLog.created_at >= start_date)
        if end_date:
            query = query.where(AuditLog.created_at <= end_date)
        if organization_id:
            try:
                query = query.where(AuditLog.organization_id == uuid.UUID(organization_id))
            except (ValueError, TypeError):
                pass

        query = query.order_by(AuditLog.created_at.asc())

        # Stream header
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "entity_type", "entity_id", "action", "actor_id", "created_at", "ip_address"])
        yield output.getvalue()
        output.truncate(0)
        output.seek(0)

        # Stream rows in batches
        offset = 0
        batch_size = 500
        while True:
            result = await self.db.execute(query.offset(offset).limit(batch_size))
            rows = result.scalars().all()
            if not rows:
                break
            for row in rows:
                writer.writerow([
                    str(row.id),
                    row.resource_type,
                    row.resource_id or "",
                    str(row.action.value if hasattr(row.action, "value") else row.action),
                    str(row.user_id) if row.user_id else "",
                    row.created_at.isoformat() if row.created_at else "",
                    row.ip_address or "",
                ])
            yield output.getvalue()
            output.truncate(0)
            output.seek(0)
            offset += batch_size
            if len(rows) < batch_size:
                break
