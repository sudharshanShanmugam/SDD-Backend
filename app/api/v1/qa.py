"""
QA test case management API routes.
"""
import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_project_access
from app.services.qa_service import QAService

logger = logging.getLogger(__name__)
router = APIRouter()


class TestCaseType(str, Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    PERFORMANCE = "performance"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    REGRESSION = "regression"


class TestCaseStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class TestRunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class TestStepRequest(BaseModel):
    step_number: int
    action: str
    expected_result: str


class TestCaseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    story_id: str
    test_type: TestCaseType = TestCaseType.UNIT
    priority: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    preconditions: str | None = None
    steps: list[TestStepRequest] = Field(default_factory=list)
    expected_outcome: str | None = None
    test_data: dict | None = None
    tags: list[str] | None = None


class TestCaseUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    test_type: TestCaseType | None = None
    priority: str | None = None
    preconditions: str | None = None
    steps: list[TestStepRequest] | None = None
    expected_outcome: str | None = None
    test_data: dict | None = None
    status: TestCaseStatus | None = None
    tags: list[str] | None = None


class TestRunCreateRequest(BaseModel):
    test_case_id: str
    run_status: TestRunStatus
    environment: str | None = None
    notes: str | None = None
    bug_ids: list[str] | None = None
    duration_seconds: int | None = None


class TestCaseResponse(BaseModel):
    id: str
    title: str
    description: str | None
    story_id: str
    test_type: str
    priority: str
    status: str
    preconditions: str | None
    steps: list[dict]
    expected_outcome: str | None
    tags: list[str]
    last_run_status: str | None
    run_count: int
    pass_rate: float | None
    created_by: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.post(
    "/test-cases",
    status_code=status.HTTP_201_CREATED,
    summary="Create test case",
)
async def create_test_case(
    payload: TestCaseCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import uuid as _uuid
    from sqlalchemy import select as _sa_select
    from app.models.user_story import UserStory as _UserStory

    try:
        story_uuid = _uuid.UUID(payload.story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story_id")

    _story_res = await db.execute(_sa_select(_UserStory).where(_UserStory.id == story_uuid))
    _story = _story_res.scalar_one_or_none()
    if not _story:
        raise HTTPException(status_code=404, detail="Story not found")

    await verify_project_access(db, project_id=str(_story.project_id), user_id=str(current_user.id))

    svc = QAService(db)
    return await svc.create_test_case(
        **payload.model_dump(),
        created_by=str(current_user.id),
    )


@router.get(
    "/test-cases",
    summary="List test cases",
)
async def list_test_cases(
    story_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    test_type: TestCaseType | None = Query(default=None),
    status: TestCaseStatus | None = Query(default=None),
    priority: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if project_id:
        await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    svc = QAService(db)
    return await svc.list_test_cases(
        user_id=str(current_user.id),
        story_id=story_id,
        project_id=project_id,
        test_type=test_type.value if test_type else None,
        status=status.value if status else None,
        priority=priority,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/test-cases/{tc_id}",
    summary="Get test case details",
)
async def get_test_case(
    tc_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = QAService(db)
    tc = await svc.get_by_id(tc_id)
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found.")
    if tc.project_id:
        await verify_project_access(db, project_id=str(tc.project_id), user_id=str(current_user.id))
    from app.services.qa_service import _serialize_tc
    return _serialize_tc(tc)


@router.patch(
    "/test-cases/{tc_id}",
    summary="Update test case",
)
async def update_test_case(
    tc_id: str,
    payload: TestCaseUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = QAService(db)
    tc = await svc.get_by_id(tc_id)
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found.")
    if tc.project_id:
        await verify_project_access(db, project_id=str(tc.project_id), user_id=str(current_user.id))
    return await svc.update_test_case(
        tc_id=tc_id,
        data=payload.model_dump(exclude_none=True),
    )


@router.delete(
    "/test-cases/{tc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete test case",
)
async def delete_test_case(
    tc_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = QAService(db)
    tc = await svc.get_by_id(tc_id)
    if not tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found.")
    if tc.project_id:
        await verify_project_access(db, project_id=str(tc.project_id), user_id=str(current_user.id))
    await svc.delete_test_case(tc_id=tc_id)


@router.post(
    "/test-runs",
    status_code=status.HTTP_201_CREATED,
    summary="Record test run result",
)
async def record_test_run(
    payload: TestRunCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the result of a test execution."""
    svc = QAService(db)
    _tc = await svc.get_by_id(payload.test_case_id)
    if not _tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found.")
    if _tc.project_id:
        await verify_project_access(db, project_id=str(_tc.project_id), user_id=str(current_user.id))
    return await svc.create_test_run(
        **payload.model_dump(),
        run_by=str(current_user.id),
    )


@router.get(
    "/test-cases/{tc_id}/runs",
    summary="Get test run history",
)
async def get_test_runs(
    tc_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the execution history for a test case."""
    svc = QAService(db)
    _tc = await svc.get_by_id(tc_id)
    if not _tc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found.")
    if _tc.project_id:
        await verify_project_access(db, project_id=str(_tc.project_id), user_id=str(current_user.id))
    return await svc.get_test_runs(tc_id=tc_id, page=page, page_size=page_size)


@router.get(
    "/coverage/{project_id}",
    summary="Get QA coverage report",
)
async def get_coverage(
    project_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return test coverage metrics for a project."""
    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    svc = QAService(db)
    return await svc.get_coverage_report(project_id=project_id)
