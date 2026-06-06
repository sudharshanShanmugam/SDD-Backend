"""
Audit log API routes.
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_admin
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "",
    summary="Query audit logs",
)
async def list_audit_logs(
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    organization_id: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Query the audit log. Admin only. Supports filtering by entity, actor, action, date range."""
    svc = AuditService(db)
    return await svc.query_logs(
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        project_id=project_id,
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/entity/{entity_type}/{entity_id}",
    summary="Get audit trail for a specific entity",
)
async def get_entity_audit_trail(
    entity_type: str,
    entity_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full audit trail for a specific entity (epic, story, requirement, etc.)."""
    svc = AuditService(db)
    return await svc.get_entity_trail(
        entity_type=entity_type,
        entity_id=entity_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/export",
    summary="Export audit logs as CSV (admin only)",
)
async def export_audit_logs(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    organization_id: str | None = Query(default=None),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Export audit logs as a downloadable CSV file."""
    from fastapi.responses import StreamingResponse
    svc = AuditService(db)
    csv_generator = await svc.export_csv(
        start_date=start_date,
        end_date=end_date,
        organization_id=organization_id,
    )
    return StreamingResponse(
        csv_generator,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )
