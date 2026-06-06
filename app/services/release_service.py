"""
Release Service.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_release(r) -> dict:
    """Serialize a Release ORM object to a frontend-friendly dict."""
    def _str(v):
        return str(v) if v is not None else None

    status_raw = r.status
    if hasattr(status_raw, "value"):
        status_raw = status_raw.value

    return {
        "id": _str(r.id),
        "name": r.name or "",
        "version": r.version or "",
        "project_id": _str(r.project_id),
        "description": r.description,
        "status": str(status_raw) if status_raw else "planning",
        "release_type": getattr(r, "release_type", "minor") or "minor",
        "target_date": r.target_date,
        "released_at": r.released_at,
        "sprint_count": 0,
        "story_count": 0,
        "created_by": _str(r.created_by),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


class ReleaseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_release(self, **kwargs) -> dict:
        from app.models.release import Release
        from app.models.project import Project

        project_id_raw = kwargs.get("project_id")
        try:
            project_uuid = uuid.UUID(project_id_raw) if isinstance(project_id_raw, str) else project_id_raw
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid project_id: {project_id_raw}") from exc

        project = await self.db.get(Project, project_uuid)
        if not project:
            raise ValueError(f"Project not found: {project_uuid}")

        # Remove fields that aren't columns on Release
        sprint_ids = kwargs.pop("sprint_ids", None)  # stored separately if needed

        release = Release(
            id=uuid.uuid4(),
            project_id=project_uuid,
            organization_id=project.organization_id,
            status="draft",
            name=kwargs.get("name"),
            version=kwargs.get("version", "0.1.0"),
            description=kwargs.get("description"),
            target_date=kwargs.get("target_date"),
            created_by=uuid.UUID(kwargs["created_by"]) if isinstance(kwargs.get("created_by"), str) else kwargs.get("created_by"),
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(release)
        await self.db.commit()
        await self.db.refresh(release)
        return _serialize_release(release)

    async def get_by_id(self, release_id: str):
        from app.models.release import Release
        try:
            release_uuid = uuid.UUID(release_id)
        except (ValueError, TypeError):
            return None
        return await self.db.get(Release, release_uuid)

    async def list_releases(
        self,
        user_id: str,
        project_id: str | None,
        status: str | None,
        release_type: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.release import Release

        query = select(Release).where(Release.deleted_at.is_(None))
        if project_id:
            try:
                query = query.where(Release.project_id == uuid.UUID(project_id))
            except (ValueError, TypeError):
                pass
        if status:
            query = query.where(Release.status == status)
        if release_type:
            query = query.where(Release.release_type == release_type)

        total = (await self.db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(Release.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_release(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def update_release(self, release_id: str, data: dict) -> dict | None:
        from app.models.release import Release
        try:
            release_uuid = uuid.UUID(release_id)
        except (ValueError, TypeError):
            return None
        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(update(Release).where(Release.id == release_uuid).values(**data))
        await self.db.commit()
        release = await self.db.get(Release, release_uuid)
        return _serialize_release(release) if release else None

    async def delete_release(self, release_id: str) -> None:
        from app.models.release import Release
        try:
            release_uuid = uuid.UUID(release_id)
        except (ValueError, TypeError):
            return
        await self.db.execute(
            update(Release)
            .where(Release.id == release_uuid)
            .values(deleted_at=datetime.now(tz=timezone.utc))
        )
        await self.db.commit()

    async def publish_release(self, release_id: str, published_by: str) -> dict | None:
        return await self.update_release(
            release_id,
            {"status": "released", "released_at": datetime.now(tz=timezone.utc).isoformat()},
        )

    async def get_changelog(self, release_id: str) -> dict:
        """Return grouped changelog for a release using ReleaseItems."""
        from app.models.release import ReleaseItem
        from app.models.user_story import UserStory

        try:
            release_uuid = uuid.UUID(release_id)
        except (ValueError, TypeError):
            return {"features": [], "bugfixes": [], "improvements": [], "others": []}

        # Get story IDs from release items
        item_result = await self.db.execute(
            select(ReleaseItem.resource_id).where(
                ReleaseItem.release_id == release_uuid,
                ReleaseItem.resource_type == "story",
            )
        )
        story_ids = [row[0] for row in item_result.all()]

        if not story_ids:
            return {"features": [], "bugfixes": [], "improvements": [], "others": []}

        story_result = await self.db.execute(
            select(UserStory).where(
                UserStory.id.in_(story_ids),
                UserStory.status == "done",
                UserStory.deleted_at.is_(None),
            )
        )
        stories = story_result.scalars().all()

        changelog: dict = {"features": [], "bugfixes": [], "improvements": [], "others": []}
        for story in stories:
            item = {"id": str(story.id), "title": story.title, "story_points": story.story_points}
            tags = list(story.tags or [])
            if "bug" in tags or "bugfix" in tags:
                changelog["bugfixes"].append(item)
            elif "feature" in tags or "new" in tags:
                changelog["features"].append(item)
            elif "improvement" in tags or "enhancement" in tags:
                changelog["improvements"].append(item)
            else:
                changelog["others"].append(item)

        return changelog
