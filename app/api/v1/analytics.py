"""
Analytics and reporting API routes.
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/dashboard",
    summary="Get dashboard summary metrics",
)
async def get_dashboard(
    organization_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return high-level dashboard metrics: active projects, sprint health, AI coverage."""
    svc = AnalyticsService(db)
    return await svc.get_dashboard(
        user_id=str(current_user.id),
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


@router.get(
    "/project/{project_id}",
    summary="Get project analytics",
)
async def get_project_analytics(
    project_id: str,
    period: str = Query(default="30d", pattern="^(7d|14d|30d|90d|all)$"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return project-level analytics:
    - Epic/story/task completion rates
    - Velocity trend
    - AI generation coverage
    - Requirement traceability
    """
    svc = AnalyticsService(db)
    return await svc.get_project_analytics(
        project_id=project_id,
        user_id=str(current_user.id),
        period=period,
    )


@router.get(
    "/sprint/{sprint_id}",
    summary="Get sprint analytics",
)
async def get_sprint_analytics(
    sprint_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return sprint analytics: burndown, velocity, scope changes."""
    svc = AnalyticsService(db)
    return await svc.get_sprint_analytics(sprint_id=sprint_id)


@router.get(
    "/team/{project_id}",
    summary="Get team performance analytics",
)
async def get_team_analytics(
    project_id: str,
    period: str = Query(default="30d", pattern="^(7d|14d|30d|90d|all)$"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return team performance: throughput, cycle time, story completion per member."""
    svc = AnalyticsService(db)
    return await svc.get_team_analytics(project_id=project_id, period=period)


@router.get(
    "/ai-usage",
    summary="Get AI usage and generation statistics",
)
async def get_ai_usage(
    organization_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    period: str = Query(default="30d", pattern="^(7d|14d|30d|90d|all)$"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return AI workflow usage metrics: token usage, generation counts, approval rates."""
    svc = AnalyticsService(db)
    return await svc.get_ai_usage(
        user_id=str(current_user.id),
        organization_id=organization_id,
        project_id=project_id,
        period=period,
    )


@router.get(
    "/requirements-traceability/{project_id}",
    summary="Get requirements traceability matrix",
)
async def get_traceability_matrix(
    project_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the requirements-to-stories-to-tasks traceability matrix."""
    svc = AnalyticsService(db)
    return await svc.get_traceability_matrix(project_id=project_id)


@router.get(
    "/velocity/{project_id}",
    summary="Get historical velocity data",
)
async def get_velocity_history(
    project_id: str,
    sprints: int = Query(default=6, ge=1, le=20),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return velocity data across the last N completed sprints."""
    svc = AnalyticsService(db)
    return await svc.get_velocity_history(project_id=project_id, sprint_count=sprints)
