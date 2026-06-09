"""
Analytics Service.
Platform analytics, project metrics, AI usage, health checks.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard(
        self,
        user_id: str,
        organization_id: str | None,
        workspace_id: str | None,
    ) -> dict:
        """High-level dashboard metrics."""
        from app.models.project import Project, ProjectMember
        from app.models.sprint import Sprint
        from app.models.story import Story

        project_query = (
            select(func.count(Project.id))
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        project_count = (await self.db.execute(project_query)).scalar_one() or 0

        active_sprints = (
            await self.db.execute(
                select(func.count(Sprint.id)).where(Sprint.status == "active")
            )
        ).scalar_one() or 0

        return {
            "total_projects": project_count,
            "active_sprints": active_sprints,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def get_project_analytics(
        self,
        project_id: str,
        user_id: str,
        period: str,
    ) -> dict:
        """Project-level analytics."""
        from app.models.story import Story
        from app.models.task import Task

        days = self._period_to_days(period)
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)

        story_result = await self.db.execute(
            select(
                func.count(Story.id).label("total"),
                func.sum(case((Story.status == "done", 1), else_=0)).label("done"),
                func.sum(Story.story_points).label("total_points"),
                func.sum(
                    case((Story.status == "done", Story.story_points), else_=0)
                ).label("done_points"),
            ).where(Story.project_id == project_id)
        )
        story_row = story_result.one()

        return {
            "project_id": project_id,
            "period": period,
            "stories": {
                "total": story_row.total or 0,
                "done": story_row.done or 0,
                "completion_rate": round((story_row.done or 0) / max(story_row.total or 1, 1) * 100, 1),
                "total_points": story_row.total_points or 0,
                "done_points": story_row.done_points or 0,
            },
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def get_sprint_analytics(self, sprint_id: str) -> dict:
        """Sprint burndown and velocity."""
        from app.models.story import Story
        from app.models.sprint import Sprint

        sprint_result = await self.db.execute(select(Sprint).where(Sprint.id == sprint_id))
        sprint = sprint_result.scalar_one_or_none()
        if not sprint:
            return {"sprint_id": sprint_id, "error": "Sprint not found"}

        story_result = await self.db.execute(
            select(
                func.count(Story.id).label("total"),
                func.sum(Story.story_points).label("total_points"),
                func.sum(
                    case((Story.status == "done", Story.story_points), else_=0)
                ).label("done_points"),
            ).where(Story.current_sprint_id == sprint_id)
        )
        row = story_result.one()

        return {
            "sprint_id": sprint_id,
            "sprint_name": sprint.name,
            "status": sprint.status,
            "total_stories": row.total or 0,
            "total_points": row.total_points or 0,
            "completed_points": row.done_points or 0,
            "remaining_points": (row.total_points or 0) - (row.done_points or 0),
            "velocity": sprint.velocity,
            "capacity_utilization": round(
                (row.done_points or 0) / max(sprint.capacity_points or 1, 1) * 100, 1
            ),
        }

    async def get_team_analytics(self, project_id: str, period: str) -> dict:
        """Team throughput and cycle time."""
        from app.models.story import Story
        from app.models.user import User

        days = self._period_to_days(period)
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(
                Story.assignee_id,
                func.count(Story.id).label("stories_completed"),
                func.sum(Story.story_points).label("points"),
            )
            .where(
                Story.project_id == project_id,
                Story.status == "done",
                Story.updated_at >= since,
                Story.assignee_id.isnot(None),
            )
            .group_by(Story.assignee_id)
        )
        rows = result.all()

        return {
            "project_id": project_id,
            "period": period,
            "team_performance": [
                {
                    "user_id": str(row[0]),
                    "stories_completed": row[1],
                    "story_points": row[2] or 0,
                }
                for row in rows
            ],
        }

    async def get_ai_usage(
        self,
        user_id: str,
        organization_id: str | None,
        project_id: str | None,
        period: str,
    ) -> dict:
        """AI generation usage metrics."""
        # Would query ai_generations table
        return {
            "period": period,
            "total_generations": 0,
            "successful_generations": 0,
            "failed_generations": 0,
            "workflows": {},
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def get_traceability_matrix(self, project_id: str) -> dict:
        """Requirements to stories to tasks traceability."""
        from app.models.requirement import Requirement
        from app.models.story import Story

        requirements = (
            await self.db.execute(
                select(Requirement).where(Requirement.project_id == project_id)
            )
        ).scalars().all()

        matrix = []
        for req in requirements:
            stories = (
                await self.db.execute(
                    select(Story).where(Story.requirement_id == req.id)
                )
            ).scalars().all()
            matrix.append({
                "requirement_id": str(req.id),
                "requirement_title": req.title,
                "stories": [{"id": str(s.id), "title": s.title} for s in stories],
                "coverage": "covered" if stories else "uncovered",
            })

        return {
            "project_id": project_id,
            "matrix": matrix,
            "coverage_summary": {
                "total": len(matrix),
                "covered": sum(1 for m in matrix if m["coverage"] == "covered"),
                "uncovered": sum(1 for m in matrix if m["coverage"] == "uncovered"),
            },
        }

    async def get_velocity_history(self, project_id: str, sprint_count: int) -> dict:
        """Historical velocity across completed sprints."""
        from app.models.sprint import Sprint

        result = await self.db.execute(
            select(Sprint)
            .where(Sprint.project_id == project_id, Sprint.status == "completed")
            .order_by(Sprint.end_date.desc())
            .limit(sprint_count)
        )
        sprints = result.scalars().all()

        return {
            "project_id": project_id,
            "sprints": [
                {
                    "sprint_id": str(s.id),
                    "sprint_name": s.name,
                    "velocity": s.velocity or 0,
                    "capacity": s.capacity_points,
                    "completed_at": s.end_date.isoformat() if s.end_date else None,
                }
                for s in reversed(sprints)
            ],
            "average_velocity": round(
                sum(s.velocity or 0 for s in sprints) / max(len(sprints), 1), 1
            ),
        }

    async def get_platform_stats(self) -> dict:
        """Platform-wide statistics for admin dashboard."""
        from app.models.user import User
        from app.models.project import Project
        from app.models.organization import Organization

        user_count = (await self.db.execute(select(func.count(User.id)))).scalar_one() or 0
        active_users = (
            await self.db.execute(
                select(func.count(User.id)).where(User.is_active == True)
            )
        ).scalar_one() or 0
        project_count = (await self.db.execute(select(func.count(Project.id)))).scalar_one() or 0
        org_count = (await self.db.execute(select(func.count(Organization.id)))).scalar_one() or 0

        return {
            "users": {"total": user_count, "active": active_users},
            "projects": project_count,
            "organizations": org_count,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def get_system_config(self) -> list:
        """List system configuration entries."""
        try:
            from app.models.system_config import SystemConfig
            result = await self.db.execute(select(SystemConfig).order_by(SystemConfig.key))
            return result.scalars().all()
        except Exception:
            return []

    async def set_system_config(
        self,
        key: str,
        value: str,
        description: str | None,
        updated_by: str,
    ) -> dict:
        """Create or update a system config entry."""
        try:
            from app.models.system_config import SystemConfig
            from sqlalchemy.dialects.postgresql import insert

            stmt = insert(SystemConfig).values(
                key=key,
                value=value,
                description=description,
                updated_by=updated_by,
                updated_at=datetime.now(tz=timezone.utc),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={"value": value, "description": description, "updated_by": updated_by},
            )
            await self.db.execute(stmt)
            await self.db.commit()
            return {"key": key, "value": value}
        except Exception as exc:
            logger.error("Failed to set system config: %s", exc)
            return {"key": key, "value": value, "error": str(exc)}

    async def get_health_status(self) -> dict:
        """Check health of all platform components."""
        components = {}

        # Database
        try:
            await self.db.execute(text("SELECT 1"))
            components["database"] = {"status": "healthy"}
        except Exception as exc:
            components["database"] = {"status": "unhealthy", "error": str(exc)}

        # Redis
        try:
            from app.services.auth_service import get_redis
            redis = await get_redis()
            await redis.ping()
            components["redis"] = {"status": "healthy"}
        except Exception as exc:
            components["redis"] = {"status": "unhealthy", "error": str(exc)}

        # Celery
        try:
            from app.workers.celery_app import celery_app
            inspect = celery_app.control.inspect(timeout=2)
            active = inspect.active()
            components["celery"] = {"status": "healthy" if active is not None else "degraded"}
        except Exception as exc:
            components["celery"] = {"status": "unhealthy", "error": str(exc)}

        overall = "healthy" if all(
            c["status"] == "healthy" for c in components.values()
        ) else "degraded"

        return {
            "status": overall,
            "components": components,
            "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    def _period_to_days(self, period: str) -> int:
        mapping = {"7d": 7, "14d": 14, "30d": 30, "90d": 90, "all": 36500}
        return mapping.get(period, 30)
