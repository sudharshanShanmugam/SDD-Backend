"""
Sprint Service.
Sprint planning, velocity tracking, board data.
"""
import logging
import uuid
from datetime import date as date_type, datetime, timezone

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_sprint(s) -> dict:
    """Serialize a Sprint ORM object to a frontend-friendly dict."""
    def _str(v):
        return str(v) if v is not None else None

    status_raw = s.status
    if hasattr(status_raw, "value"):
        status_raw = status_raw.value

    # start_date / end_date may be date or str
    def _date_str(v):
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, (date_type, datetime)):
            return v.isoformat()
        return str(v)

    return {
        # ── identity ──────────────────────────────────────────────────────
        "id": str(s.id),
        "name": s.name or "",
        "status": str(status_raw) if status_raw else "planned",
        "goal": s.goal,
        # ── camelCase date / FK fields (match TypeScript SprintSummary) ───
        "startDate": _date_str(s.start_date),
        "endDate": _date_str(s.end_date),
        "projectId": str(s.project_id),
        "organizationId": str(s.organization_id),
        "sprintNumber": s.sprint_number,
        "capacityPoints": s.capacity_points,
        "committedPoints": s.committed_points or 0,
        "completedPoints": s.completed_points or 0,
        "velocity": s.velocity,
        # ── SprintSummary aggregate fields (zero until stories are loaded) ─
        "storyCount": 0,
        "totalStoryPoints": s.committed_points or 0,
        "completedStoryPoints": s.completed_points or 0,
        # ── audit ──────────────────────────────────────────────────────────
        "createdAt": s.created_at.isoformat() if s.created_at else None,
        "updatedAt": s.updated_at.isoformat() if s.updated_at else None,
    }


class SprintService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_sprint(self, **kwargs) -> dict:
        from app.models.sprint import Sprint
        from app.models.project import Project

        # Resolve project → get organization_id
        project_id_raw = kwargs.get("project_id")
        try:
            project_uuid = uuid.UUID(project_id_raw) if isinstance(project_id_raw, str) else project_id_raw
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid project_id: {project_id_raw}") from exc

        project = await self.db.get(Project, project_uuid)
        if not project:
            raise ValueError(f"Project not found: {project_uuid}")

        # Auto-assign sprint_number
        count_result = await self.db.execute(
            select(func.count()).select_from(Sprint).where(Sprint.project_id == project_uuid)
        )
        sprint_number = (count_result.scalar() or 0) + 1

        # Parse date strings
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        if isinstance(start_date, str) and start_date:
            start_date = date_type.fromisoformat(start_date)
        if isinstance(end_date, str) and end_date:
            end_date = date_type.fromisoformat(end_date)

        sprint = Sprint(
            id=uuid.uuid4(),
            project_id=project_uuid,
            organization_id=project.organization_id,
            sprint_number=sprint_number,
            name=kwargs.get("name", f"Sprint {sprint_number}"),
            goal=kwargs.get("goal"),
            start_date=start_date,
            end_date=end_date,
            capacity_points=kwargs.get("capacity_points"),
            status="planning",
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(sprint)
        await self.db.commit()
        await self.db.refresh(sprint)
        return _serialize_sprint(sprint)

    async def get_by_id(self, sprint_id: str):
        from app.models.sprint import Sprint
        try:
            sprint_uuid = uuid.UUID(sprint_id)
        except (ValueError, TypeError):
            return None
        return await self.db.get(Sprint, sprint_uuid)

    async def list_sprints(
        self,
        user_id: str,
        project_id: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.sprint import Sprint

        query = select(Sprint).where(Sprint.deleted_at.is_(None))
        if project_id:
            try:
                query = query.where(Sprint.project_id == uuid.UUID(project_id))
            except (ValueError, TypeError):
                pass
        if status:
            query = query.where(Sprint.status == status)

        total = (await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(Sprint.sprint_number.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_sprint(s) for s in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def update_sprint(self, sprint_id: str, data: dict):
        from app.models.sprint import Sprint
        try:
            sprint_uuid = uuid.UUID(sprint_id)
        except (ValueError, TypeError):
            return None

        # Parse date strings in update data
        for key in ("start_date", "end_date"):
            if key in data and isinstance(data[key], str) and data[key]:
                data[key] = date_type.fromisoformat(data[key])

        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(
            update(Sprint).where(Sprint.id == sprint_uuid).values(**data)
        )
        await self.db.commit()
        sprint = await self.db.get(Sprint, sprint_uuid)
        return _serialize_sprint(sprint) if sprint else None

    async def delete_sprint(self, sprint_id: str) -> None:
        from app.models.sprint import Sprint
        from app.models.user_story import UserStory
        try:
            sprint_uuid = uuid.UUID(sprint_id)
        except (ValueError, TypeError):
            return
        now = datetime.now(tz=timezone.utc)
        # Unassign stories before soft-deleting so they return to the backlog
        await self.db.execute(
            update(UserStory)
            .where(UserStory.current_sprint_id == sprint_uuid, UserStory.deleted_at.is_(None))
            .values(current_sprint_id=None, updated_at=now)
        )
        await self.db.execute(
            update(Sprint)
            .where(Sprint.id == sprint_uuid)
            .values(deleted_at=now)
        )
        await self.db.commit()

    async def start_sprint(self, sprint_id: str, goal: str | None, started_by: str):
        updates: dict = {"status": "active"}
        if goal:
            updates["goal"] = goal
        return await self.update_sprint(sprint_id, updates)

    async def complete_sprint(
        self,
        sprint_id: str,
        incomplete_action: str,
        next_sprint_id: str | None,
        completed_by: str,
    ):
        from app.models.user_story import UserStory

        try:
            sprint_uuid = uuid.UUID(sprint_id)
        except (ValueError, TypeError):
            return None

        # Handle incomplete stories using UserStory model
        incomplete_stories = (
            await self.db.execute(
                select(UserStory).where(
                    UserStory.current_sprint_id == sprint_uuid,
                    UserStory.status.notin_(["done", "cancelled"]),
                    UserStory.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        for story in incomplete_stories:
            if incomplete_action == "next_sprint" and next_sprint_id:
                try:
                    next_uuid = uuid.UUID(next_sprint_id)
                    await self.db.execute(
                        update(UserStory)
                        .where(UserStory.id == story.id)
                        .values(current_sprint_id=next_uuid)
                    )
                except (ValueError, TypeError):
                    pass
            # "backlog" action: keep current_sprint_id intact so the completed
            # sprint retains its story history. The planning page backlog shows
            # stories from completed sprints as available for re-assignment.

        # Calculate velocity before completing (sum of story_points for done stories)
        velocity_result = await self.db.execute(
            select(func.sum(UserStory.story_points)).where(
                UserStory.current_sprint_id == sprint_uuid,
                UserStory.status == "done",
                UserStory.deleted_at.is_(None),
            )
        )
        velocity = float(velocity_result.scalar_one_or_none() or 0)

        updates = {
            "status": "completed",
            "velocity": velocity,
            "completed_points": int(velocity),
        }
        return await self.update_sprint(sprint_id, updates)

    async def get_velocity_data(self, sprint_id: str) -> dict:
        """Return velocity and burndown data for a sprint."""
        from app.models.user_story import UserStory

        try:
            sprint_uuid = uuid.UUID(sprint_id)
        except (ValueError, TypeError):
            return {"sprint_id": sprint_id, "total_stories": 0, "total_points": 0,
                    "completed_points": 0, "remaining_points": 0, "completion_percentage": 0.0}

        result = await self.db.execute(
            select(
                func.count(UserStory.id).label("total_stories"),
                func.sum(UserStory.story_points).label("total_points"),
                func.sum(
                    case(
                        (UserStory.status == "done", UserStory.story_points),
                        else_=0,
                    )
                ).label("completed_points"),
            ).where(
                UserStory.current_sprint_id == sprint_uuid,
                UserStory.deleted_at.is_(None),
            )
        )
        row = result.one()

        total_pts = row.total_points or 0
        completed_pts = row.completed_points or 0
        return {
            "sprint_id": sprint_id,
            "total_stories": row.total_stories or 0,
            "total_points": total_pts,
            "completed_points": completed_pts,
            "remaining_points": total_pts - completed_pts,
            "completion_percentage": (
                round(completed_pts / total_pts * 100, 1) if total_pts > 0 else 0.0
            ),
        }

    async def get_board_data(self, sprint_id: str) -> dict:
        """Return Kanban board data grouped by status."""
        from app.models.user_story import UserStory
        from app.api.v1.stories import _serialize_story

        try:
            sprint_uuid = uuid.UUID(sprint_id)
        except (ValueError, TypeError):
            return {"sprint_id": sprint_id, "columns": {}}

        statuses = ["backlog", "todo", "in_progress", "review", "done"]
        board: dict = {}

        for st in statuses:
            stories = (
                await self.db.execute(
                    select(UserStory)
                    .where(
                        UserStory.current_sprint_id == sprint_uuid,
                        UserStory.status == st,
                        UserStory.deleted_at.is_(None),
                    )
                    .order_by(UserStory.story_points.desc().nullslast())
                )
            ).scalars().all()
            board[st] = [_serialize_story(s) for s in stories]

        return {"sprint_id": sprint_id, "columns": board}
