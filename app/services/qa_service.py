"""
QA Service.
Test case management, coverage reporting.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_tc(tc) -> dict:
    """Serialize a QATestCase ORM object to a frontend-friendly dict."""
    def _str(v):
        return str(v) if v is not None else None

    status_raw = tc.status
    if hasattr(status_raw, "value"):
        status_raw = status_raw.value

    priority_raw = tc.priority
    if hasattr(priority_raw, "value"):
        priority_raw = priority_raw.value

    test_type_raw = tc.test_type
    if hasattr(test_type_raw, "value"):
        test_type_raw = test_type_raw.value

    return {
        "id": str(tc.id),
        "tc_number": tc.tc_number or "",
        "title": tc.title or "",
        "description": tc.description,
        "story_id": _str(tc.user_story_id),
        "project_id": _str(tc.project_id),
        "requirement_id": _str(tc.requirement_id),
        "test_type": str(test_type_raw) if test_type_raw else "functional",
        "status": str(status_raw) if status_raw else "draft",
        "priority": str(priority_raw) if priority_raw else "medium",
        "preconditions": tc.preconditions,
        "expected_result": tc.expected_result,
        "actual_result": tc.actual_result,
        "is_automated": tc.is_automated,
        "is_ai_generated": tc.is_ai_generated,
        "tags": tc.tags or [],
        "created_by": _str(tc.created_by),
        "created_at": tc.created_at.isoformat() if tc.created_at else None,
        "updated_at": tc.updated_at.isoformat() if tc.updated_at else None,
    }


class QAService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_test_case(self, **kwargs) -> dict:
        from app.models.qa_test_case import QATestCase

        # Map frontend field names → DB column names
        story_id_raw = kwargs.get("story_id")
        try:
            story_uuid = uuid.UUID(story_id_raw) if story_id_raw else None
        except (ValueError, TypeError):
            story_uuid = None

        # Get project_id and org_id from the story
        project_uuid = None
        org_uuid = None
        if story_uuid:
            from app.models.user_story import UserStory
            story = await self.db.get(UserStory, story_uuid)
            if story:
                project_uuid = story.project_id
                org_uuid = story.organization_id

        # Auto-generate tc_number
        count_result = await self.db.execute(
            select(func.count()).select_from(QATestCase)
            .where(QATestCase.project_id == project_uuid) if project_uuid else
            select(func.count()).select_from(QATestCase)
        )
        tc_count = count_result.scalar() or 0
        tc_number = f"TC-{tc_count + 1:03d}"

        created_by_raw = kwargs.get("created_by")
        try:
            created_by_uuid = uuid.UUID(created_by_raw) if created_by_raw else None
        except (ValueError, TypeError):
            created_by_uuid = None

        tc = QATestCase(
            id=uuid.uuid4(),
            user_story_id=story_uuid,
            project_id=project_uuid,
            organization_id=org_uuid,
            tc_number=tc_number,
            title=kwargs.get("title", ""),
            description=kwargs.get("description"),
            test_type=kwargs.get("test_type", "functional"),
            priority=kwargs.get("priority", "medium"),
            status="draft",
            preconditions=kwargs.get("preconditions"),
            expected_result=kwargs.get("expected_outcome") or kwargs.get("expected_result"),
            tags=kwargs.get("tags") or [],
            is_automated=False,
            is_ai_generated=False,
            created_by=created_by_uuid,
            updated_by=created_by_uuid,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(tc)
        await self.db.commit()
        await self.db.refresh(tc)
        return _serialize_tc(tc)

    async def get_by_id(self, tc_id: str):
        from app.models.qa_test_case import QATestCase
        try:
            tc_uuid = uuid.UUID(tc_id)
        except (ValueError, TypeError):
            return None
        return await self.db.get(QATestCase, tc_uuid)

    async def list_test_cases(
        self,
        user_id: str,
        story_id: str | None,
        project_id: str | None,
        test_type: str | None,
        status: str | None,
        priority: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.qa_test_case import QATestCase

        query = select(QATestCase).where(QATestCase.deleted_at.is_(None))
        if story_id:
            try:
                query = query.where(QATestCase.user_story_id == uuid.UUID(story_id))
            except (ValueError, TypeError):
                pass
        if project_id:
            try:
                query = query.where(QATestCase.project_id == uuid.UUID(project_id))
            except (ValueError, TypeError):
                pass
        if test_type:
            query = query.where(QATestCase.test_type == test_type)
        if status:
            query = query.where(QATestCase.status == status)
        if priority:
            query = query.where(QATestCase.priority == priority)

        total = (await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )).scalar_one()
        items = (
            await self.db.execute(
                query.order_by(QATestCase.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "items": [_serialize_tc(tc) for tc in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def update_test_case(self, tc_id: str, data: dict) -> dict | None:
        from app.models.qa_test_case import QATestCase

        try:
            tc_uuid = uuid.UUID(tc_id)
        except (ValueError, TypeError):
            return None

        # Map field aliases
        if "expected_outcome" in data:
            data["expected_result"] = data.pop("expected_outcome")
        if "story_id" in data:
            data.pop("story_id")  # read-only

        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(
            update(QATestCase).where(QATestCase.id == tc_uuid).values(**data)
        )
        await self.db.commit()
        tc = await self.db.get(QATestCase, tc_uuid)
        return _serialize_tc(tc) if tc else None

    async def delete_test_case(self, tc_id: str) -> None:
        from app.models.qa_test_case import QATestCase

        try:
            tc_uuid = uuid.UUID(tc_id)
        except (ValueError, TypeError):
            return
        await self.db.execute(
            update(QATestCase)
            .where(QATestCase.id == tc_uuid)
            .values(deleted_at=datetime.now(tz=timezone.utc))
        )
        await self.db.commit()

    async def create_test_run(self, **kwargs) -> dict:
        """Record a test run by updating the test case status."""
        from app.models.qa_test_case import QATestCase

        tc_id = kwargs.get("test_case_id")
        run_status = kwargs.get("run_status", "passed")
        notes = kwargs.get("notes")

        # Map run_status to test case status
        status_map = {"passed": "active", "failed": "active", "blocked": "draft", "skipped": "draft"}
        new_status = status_map.get(str(run_status), "active")

        try:
            tc_uuid = uuid.UUID(tc_id) if tc_id else None
        except (ValueError, TypeError):
            tc_uuid = None

        if tc_uuid:
            await self.db.execute(
                update(QATestCase)
                .where(QATestCase.id == tc_uuid)
                .values(
                    status=new_status,
                    actual_result=notes,
                    updated_at=datetime.now(tz=timezone.utc),
                )
            )
            await self.db.commit()

        return {
            "test_case_id": tc_id,
            "run_status": run_status,
            "environment": kwargs.get("environment"),
            "notes": notes,
            "run_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def get_test_runs(self, tc_id: str, page: int, page_size: int) -> dict:
        """Return empty list since there's no TestRun table yet."""
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    async def get_coverage_report(self, project_id: str) -> dict:
        """Return QA coverage metrics for a project."""
        from app.models.qa_test_case import QATestCase
        from app.models.user_story import UserStory

        try:
            project_uuid = uuid.UUID(project_id)
        except (ValueError, TypeError):
            return {"project_id": project_id, "total_stories": 0, "covered_stories": 0,
                    "coverage_percentage": 0.0, "total_test_cases": 0, "passing_test_cases": 0,
                    "pass_rate": 0.0}

        # Count stories for project
        story_count = (
            await self.db.execute(
                select(func.count(UserStory.id)).where(
                    UserStory.project_id == project_uuid,
                    UserStory.deleted_at.is_(None),
                )
            )
        ).scalar_one() or 0

        # Stories with at least one test case
        covered_count = (
            await self.db.execute(
                select(func.count(func.distinct(QATestCase.user_story_id)))
                .where(
                    QATestCase.project_id == project_uuid,
                    QATestCase.deleted_at.is_(None),
                    QATestCase.user_story_id.isnot(None),
                )
            )
        ).scalar_one() or 0

        tc_count = (
            await self.db.execute(
                select(func.count(QATestCase.id)).where(
                    QATestCase.project_id == project_uuid,
                    QATestCase.deleted_at.is_(None),
                )
            )
        ).scalar_one() or 0

        # Consider "active" status as "passing" (test ran successfully)
        passed = (
            await self.db.execute(
                select(func.count(QATestCase.id)).where(
                    QATestCase.project_id == project_uuid,
                    QATestCase.status == "active",
                    QATestCase.deleted_at.is_(None),
                )
            )
        ).scalar_one() or 0

        return {
            "project_id": project_id,
            "total_stories": story_count,
            "covered_stories": covered_count,
            "coverage_percentage": round(covered_count / max(story_count, 1) * 100, 1),
            "total_test_cases": tc_count,
            "passing_test_cases": passed,
            "pass_rate": round(passed / max(tc_count, 1) * 100, 1),
        }
