"""
AI orchestration API routes.
Triggers LangGraph workflows, manages AI generations and prompt templates.
"""
import logging
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_project_access
from app.workers.tasks.ai_tasks import (
    generate_api_spec,
    generate_epics,
    generate_qa_cases,
    generate_release_notes,
    generate_sprint_plan,
    generate_stories,
    generate_tasks,
    generate_ui_spec,
    run_requirement_extraction,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ExtractionConfig(BaseModel):
    extract_functional: bool = True
    extract_non_functional: bool = True
    extract_business: bool = True
    auto_generate_epics: bool = False
    prompt_override: str | None = None


class EpicGenerationConfig(BaseModel):
    max_epics: int = Field(default=10, ge=1, le=50)
    include_api_specs: bool = False
    include_ui_specs: bool = False
    context: str | None = None


class StoryGenerationConfig(BaseModel):
    max_stories: int = Field(default=20, ge=1, le=100)
    include_acceptance_criteria: bool = True
    story_format: str = Field(default="standard", pattern="^(standard|jobs_to_be_done|bdd)$")


class SprintPlanConfig(BaseModel):
    sprint_duration_days: int = Field(default=14, ge=7, le=42)
    team_capacity_points: int = Field(default=40, ge=1, le=500)
    include_buffer: bool = True
    prioritization_strategy: str = Field(
        default="value_effort",
        pattern="^(value_effort|priority|dependencies|moscow)$",
    )


class TaskGenerationConfig(BaseModel):
    max_tasks: int = Field(default=10, ge=1, le=50)
    include_estimates: bool = True
    include_dependencies: bool = True


class PromptTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    workflow_type: str
    prompt_text: str = Field(min_length=1)
    variables: list[str] | None = None
    is_active: bool = True
    description: str | None = None


class WorkflowStatusResponse(BaseModel):
    run_id: str
    workflow_type: str
    status: str
    progress: int
    current_step: str | None
    result: dict | None
    error: str | None
    started_at: str
    completed_at: str | None


# ── Extraction ─────────────────────────────────────────────────────────────────

@router.post(
    "/extract-requirements/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Extract requirements from a document",
)
async def extract_requirements(
    document_id: str,
    config: ExtractionConfig = ExtractionConfig(),
    project_id: str | None = Query(default=None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger the LangGraph requirement extraction workflow for a document.
    Returns a run_id to track workflow progress.
    """
    if project_id:
        await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    task = run_requirement_extraction.delay(
        document_id=document_id,
        project_id=project_id,
        config=config.model_dump(),
        initiated_by=str(current_user.id),
    )
    return {
        "run_id": task.id,
        "document_id": document_id,
        "status": "queued",
        "message": "Requirement extraction workflow triggered.",
    }


@router.get(
    "/workflow-status/{run_id}",
    response_model=WorkflowStatusResponse,
    summary="Check workflow progress",
)
async def get_workflow_status(
    run_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll the status of an AI workflow run by its Celery task ID."""
    from celery.result import AsyncResult
    from app.workers.celery_app import celery_app

    result = AsyncResult(run_id, app=celery_app)

    if result.state == "PENDING":
        return WorkflowStatusResponse(
            run_id=run_id,
            workflow_type="unknown",
            status="queued",
            progress=0,
            current_step=None,
            result=None,
            error=None,
            started_at="",
            completed_at=None,
        )

    meta = result.info or {}
    if isinstance(meta, Exception):
        return WorkflowStatusResponse(
            run_id=run_id,
            workflow_type=meta.get("workflow_type", "unknown") if isinstance(meta, dict) else "unknown",
            status="failed",
            progress=0,
            current_step=None,
            result=None,
            error=str(meta),
            started_at=meta.get("started_at", "") if isinstance(meta, dict) else "",
            completed_at=None,
        )

    return WorkflowStatusResponse(
        run_id=run_id,
        workflow_type=meta.get("workflow_type", "unknown"),
        status=result.state.lower(),
        progress=meta.get("progress", 0),
        current_step=meta.get("current_step"),
        result=meta.get("result"),
        error=meta.get("error"),
        started_at=meta.get("started_at", ""),
        completed_at=meta.get("completed_at"),
    )


# ── Generation ─────────────────────────────────────────────────────────────────

@router.post(
    "/generate-epics/{project_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate epics from project requirements",
)
async def trigger_generate_epics(
    project_id: str,
    config: EpicGenerationConfig = EpicGenerationConfig(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate epics using AI from analyzed requirements."""
    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    task = generate_epics.delay(
        project_id=project_id,
        config=config.model_dump(),
        initiated_by=str(current_user.id),
    )
    return {"run_id": task.id, "project_id": project_id, "status": "queued"}


@router.post(
    "/generate-stories/{epic_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate user stories from an epic",
)
async def trigger_generate_stories(
    epic_id: str,
    config: StoryGenerationConfig = StoryGenerationConfig(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate user stories for an epic using AI."""
    from app.models.epic import Epic as _Epic
    from sqlalchemy import select as _sa_select
    try:
        _epic_uuid = uuid.UUID(epic_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid epic_id")
    _epic_res = await db.execute(_sa_select(_Epic).where(_Epic.id == _epic_uuid))
    _epic = _epic_res.scalar_one_or_none()
    if not _epic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Epic not found.")
    await verify_project_access(db, project_id=str(_epic.project_id), user_id=str(current_user.id))
    task = generate_stories.delay(
        epic_id=epic_id,
        config=config.model_dump(),
        initiated_by=str(current_user.id),
    )
    return {"run_id": task.id, "epic_id": epic_id, "status": "queued"}


class PlanSprintsRequest(BaseModel):
    """
    Synchronous AI sprint planner.
    velocity / sprint_count are derived server-side from team_size;
    they are accepted here only for backward-compat overrides.
    """

    project_id: str = Field(alias="projectId")
    team_size: int = Field(default=3, ge=1, le=50, alias="teamSize")
    sprint_length_weeks: int = Field(default=2, ge=1, le=4, alias="sprintLengthWeeks")
    # Optional overrides — 0 means "auto-calculate"
    velocity_override: int = Field(default=0, ge=0, le=500, alias="velocityOverride")

    model_config = {"populate_by_name": True}


class SprintAssignment(BaseModel):
    sprint_id: str = Field(alias="sprintId")
    story_ids: list[str] = Field(alias="storyIds")
    sprint_name: str = Field(alias="sprintName")
    sprint_goal: str = Field(alias="sprintGoal")
    committed_points: int = Field(alias="committedPoints")
    risks: list[dict] = []
    estimated_points_updated: list[dict] = Field(
        default_factory=list,
        alias="estimatedPointsUpdated",
        description="Stories whose story_points were set by the AI",
    )

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


@router.post(
    "/plan-sprints",
    summary="AI sprint planning — auto-calculates velocity & sprints, assigns every story",
    response_model=list[SprintAssignment],
)
async def plan_sprints_sync(
    payload: PlanSprintsRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Full-backlog sprint planner:

    1. Auto-calculates velocity from team_size (8 pts/dev/week × sprint_length × 80% efficiency).
    2. Auto-calculates sprint count = ceil(total_story_points / velocity).
    3. Assigns a default 3 pts to any unestimated story.
    4. Bin-packs ALL backlog stories into sprints by priority (no story left behind).
    5. Calls the LLM with a compact summary (titles only) to generate sprint goals & risks.
    6. Persists sprint rows, story assignments, and default story-point estimates.
    """
    import math
    import json as _json
    from app.models.user_story import UserStory
    from app.models.sprint import Sprint
    from app.models.project import Project
    from langchain_openai import ChatOpenAI
    from datetime import datetime, timezone

    # ─── constants & helpers ──────────────────────────────────────────────────
    POINTS_PER_DEV_PER_WEEK = 8   # conservative: accounts for code-review, standups
    OVERHEAD                 = 0.80
    DEFAULT_SP               = 3  # Fibonacci default for unestimated stories
    PRIORITY_RANK            = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def _ev(v, fb: str = "") -> str:
        if v is None:
            return fb
        return v.value if hasattr(v, "value") else str(v)

    # ─── 1. Validate project ──────────────────────────────────────────────────
    try:
        project_uuid = uuid.UUID(payload.project_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid project_id")
    project = await db.get(Project, project_uuid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await verify_project_access(db, project_id=payload.project_id, user_id=str(current_user.id))

    # ─── 2. Load ALL backlog stories ──────────────────────────────────────────
    result = await db.execute(
        select(UserStory).where(
            UserStory.project_id == project_uuid,
            UserStory.current_sprint_id.is_(None),
            UserStory.deleted_at.is_(None),
            UserStory.status.notin_(["done", "cancelled"]),
        ).order_by(UserStory.created_at.asc())
    )
    stories: list[UserStory] = list(result.scalars().all())
    if not stories:
        raise HTTPException(status_code=422, detail="No unassigned backlog stories found.")

    # ─── 3. Effective velocity (team-size driven) ─────────────────────────────
    auto_vel = int(
        payload.team_size * POINTS_PER_DEV_PER_WEEK
        * payload.sprint_length_weeks * OVERHEAD
    )
    effective_velocity = (
        payload.velocity_override if payload.velocity_override > 0 else max(auto_vel, 1)
    )

    # ─── 4. Story-points map (fill defaults for unestimated) ─────────────────
    sp_map: dict[str, int] = {
        str(s.id): (s.story_points if s.story_points is not None else DEFAULT_SP)
        for s in stories
    }
    total_points = sum(sp_map.values())

    # ─── 5. Auto sprint count: enough sprints to fit all stories ─────────────
    sprint_count = max(1, min(52, math.ceil(total_points / effective_velocity)))

    logger.info(
        "plan-sprints: team=%d devs | velocity=%d pts/sprint | "
        "%d stories / %d total pts → %d sprints",
        payload.team_size, effective_velocity, len(stories), total_points, sprint_count,
    )

    # ─── 6. Sort: priority asc then story-size desc (First-Fit Decreasing) ───
    stories_sorted = sorted(
        stories,
        key=lambda s: (PRIORITY_RANK.get(_ev(s.priority, "medium"), 2), -(sp_map[str(s.id)])),
    )

    # ─── 7. Bin-pack ALL stories into sprint slots ────────────────────────────
    sprint_story_map: list[list[UserStory]] = [[] for _ in range(sprint_count)]
    sprint_used:      list[int]             = [0] * sprint_count

    for story in stories_sorted:
        sp = sp_map[str(story.id)]
        placed = False
        for i in range(sprint_count):
            if sprint_used[i] + sp <= effective_velocity:
                sprint_story_map[i].append(story)
                sprint_used[i] += sp
                placed = True
                break
        if not placed:
            # Story is larger than one full sprint — add to least-loaded sprint
            idx = min(range(sprint_count), key=lambda i: sprint_used[i])
            sprint_story_map[idx].append(story)
            sprint_used[idx] += sp

    # ─── 8. Create / reuse Sprint DB rows ────────────────────────────────────
    existing_r = await db.execute(
        select(Sprint).where(
            Sprint.project_id == project_uuid,
            Sprint.deleted_at.is_(None),
        ).order_by(Sprint.sprint_number.asc())
    )
    existing_sprints: list[Sprint] = list(existing_r.scalars().all())

    today      = date.today()
    sprint_rows: list[Sprint] = []
    new_count  = 0

    for i in range(sprint_count):
        if i < len(existing_sprints):
            sprint_rows.append(existing_sprints[i])
        else:
            snum   = len(existing_sprints) + new_count + 1
            new_count += 1
            s_start = today + timedelta(weeks=payload.sprint_length_weeks * i)
            s_end   = s_start + timedelta(weeks=payload.sprint_length_weeks) - timedelta(days=1)
            row = Sprint(
                id=uuid.uuid4(),
                project_id=project_uuid,
                organization_id=project.organization_id,
                sprint_number=snum,
                name=f"Sprint {snum}",
                goal=None,
                start_date=s_start,
                end_date=s_end,
                capacity_points=effective_velocity,
                status="planning",
            )
            db.add(row)
            sprint_rows.append(row)

    if new_count:
        await db.flush()

    # ─── 9. AI: sprint goals & risks (compact payload — only titles) ──────────
    ai_meta: dict[int, dict] = {}   # sprint_number → {sprint_name, sprint_goal, risks}
    try:
        from app.ai.config import AIConfig
        llm = ChatOpenAI(
            model=AIConfig._LLM_MODEL,
            temperature=0.2,
            max_tokens=1024,
            api_key=AIConfig.DEEPINFRA_API_KEY,
            base_url=AIConfig.DEEPINFRA_BASE_URL,
            timeout=60,
            max_retries=0,  # no retries — fail fast so the endpoint stays under 2 min total
        )

        # Cap at 20 sprints per AI call to keep the prompt small and fast.
        # Goals for any remaining sprints get the default "Sprint N delivery" text.
        MAX_AI_SPRINTS = 20
        summaries = []
        for i, s_stories in enumerate(sprint_story_map[:MAX_AI_SPRINTS]):
            titles = [
                f"  - {s.story_number or ('US-' + str(s.id)[:6])}: {(s.title or '')[:50]}"
                for s in s_stories[:8]   # 8 titles per sprint is plenty for a goal
            ]
            extra = len(s_stories) - 8
            summaries.append({
                "sprint_number": i + 1,
                "story_count": len(s_stories),
                "stories_preview": titles + ([f"  ... +{extra} more"] if extra > 0 else []),
            })

        prompt = (
            f"You are a Scrum Master. Team: {payload.team_size} dev(s), "
            f"{payload.sprint_length_weeks}-week sprints, {effective_velocity} pts/sprint.\n\n"
            f"Write a short sprint name and one-sentence stakeholder goal for each sprint below. "
            f"Optionally add 1-2 risks as objects with keys: description (string), "
            f"probability (low|medium|high), impact (low|medium|high).\n\n"
            f"Sprints:\n{_json.dumps(summaries, indent=2)}\n\n"
            f'Respond ONLY with valid JSON:\n'
            f'{{"sprints":[{{"sprint_number":1,"sprint_name":"...","sprint_goal":"...",'
            f'"risks":[{{"description":"...","probability":"medium","impact":"medium"}}]}}]}}'
        )

        response = await llm.ainvoke(prompt)
        raw = response.content if isinstance(response.content, str) else str(response.content)
        si, ei = raw.find("{"), raw.rfind("}")
        if si != -1 and ei > si:
            raw = raw[si : ei + 1]
        parsed = _json.loads(raw)
        for item in parsed.get("sprints", []):
            # Normalise risks: LLM sometimes returns strings instead of dicts
            raw_risks = item.get("risks") or []
            normalized: list[dict] = []
            for r in raw_risks:
                if isinstance(r, dict):
                    normalized.append(r)
                elif isinstance(r, str) and r.strip():
                    normalized.append({
                        "description": r.strip(),
                        "probability": "medium",
                        "impact": "medium",
                    })
            item["risks"] = normalized
            ai_meta[item.get("sprint_number", 0)] = item

    except Exception as exc:
        logger.warning("AI goals call failed (%s) — using default sprint goals", exc)

    # ─── 10. Persist: update sprints, assign stories, store default points ────
    now = datetime.now(tz=timezone.utc)
    assignments: list[SprintAssignment] = []
    total_pts_updated: list[dict] = []

    for i, sprint_row in enumerate(sprint_rows):
        meta     = ai_meta.get(i + 1, {})
        ai_goal  = meta.get("sprint_goal", "") or f"Sprint {i + 1} delivery"
        ai_name  = meta.get("sprint_name", "") or sprint_row.name
        # Ensure risks is always a list of dicts (defensive, in case AI call was skipped)
        raw_risks = meta.get("risks") or []
        ai_risks: list[dict] = [
            r if isinstance(r, dict) else {"description": str(r), "probability": "low", "impact": "low"}
            for r in raw_risks
            if r
        ]
        committed = sprint_used[i]

        await db.execute(
            update(Sprint)
            .where(Sprint.id == sprint_row.id)
            .values(
                name=ai_name,
                goal=ai_goal,
                capacity_points=effective_velocity,
                committed_points=committed,
                updated_at=now,
            )
        )

        assigned_ids: list[str] = []
        sprint_pts_updated: list[dict] = []

        for story in sprint_story_map[i]:
            sid = str(story.id)
            if sid in assigned_ids:
                continue
            assigned_ids.append(sid)

            await db.execute(
                update(UserStory)
                .where(UserStory.id == story.id)
                .values(current_sprint_id=sprint_row.id, updated_at=now)
            )

            # Persist default story points for unestimated stories
            if story.story_points is None:
                await db.execute(
                    update(UserStory)
                    .where(UserStory.id == story.id)
                    .values(story_points=DEFAULT_SP, updated_at=now)
                )
                entry = {
                    "storyId": sid,
                    "identifier": story.story_number or sid[:8],
                    "title": story.title,
                    "estimatedPoints": DEFAULT_SP,
                }
                sprint_pts_updated.append(entry)
                total_pts_updated.append(entry)

        assignments.append(
            SprintAssignment(
                sprintId=str(sprint_row.id),
                storyIds=assigned_ids,
                sprintName=ai_name,
                sprintGoal=ai_goal,
                committedPoints=committed,
                risks=ai_risks,
                estimatedPointsUpdated=sprint_pts_updated,
            )
        )

    await db.commit()

    logger.info(
        "Sprint plan done: %d sprints | %d/%d stories assigned | %d pts estimated | vel=%d",
        len(assignments),
        sum(len(a.story_ids) for a in assignments),
        len(stories),
        len(total_pts_updated),
        effective_velocity,
    )
    return assignments


@router.post(
    "/generate-sprint-plan/{project_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate AI sprint plan",
)
async def trigger_sprint_plan(
    project_id: str,
    config: SprintPlanConfig = SprintPlanConfig(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI-generate an optimal sprint plan from the backlog."""
    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    task = generate_sprint_plan.delay(
        project_id=project_id,
        config=config.model_dump(),
        initiated_by=str(current_user.id),
    )
    return {"run_id": task.id, "project_id": project_id, "status": "queued"}


@router.post(
    "/generate-tasks/{story_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate development tasks from a user story",
)
async def trigger_generate_tasks(
    story_id: str,
    config: TaskGenerationConfig = TaskGenerationConfig(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user_story import UserStory as _UserStory
    from sqlalchemy import select as _sa_select
    try:
        _story_uuid = uuid.UUID(story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story_id")
    _story_res = await db.execute(_sa_select(_UserStory).where(_UserStory.id == _story_uuid))
    _story = _story_res.scalar_one_or_none()
    if not _story:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")
    await verify_project_access(db, project_id=str(_story.project_id), user_id=str(current_user.id))
    task = generate_tasks.delay(
        story_id=story_id,
        config=config.model_dump(),
        initiated_by=str(current_user.id),
    )
    return {"run_id": task.id, "story_id": story_id, "status": "queued"}


@router.post(
    "/generate-qa/{story_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate QA test cases for a story",
)
async def trigger_generate_qa(
    story_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user_story import UserStory as _UserStory
    from sqlalchemy import select as _sa_select
    try:
        _story_uuid = uuid.UUID(story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story_id")
    _story_res = await db.execute(_sa_select(_UserStory).where(_UserStory.id == _story_uuid))
    _story = _story_res.scalar_one_or_none()
    if not _story:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")
    await verify_project_access(db, project_id=str(_story.project_id), user_id=str(current_user.id))
    task = generate_qa_cases.delay(
        story_id=story_id,
        initiated_by=str(current_user.id),
    )
    return {"run_id": task.id, "story_id": story_id, "status": "queued"}


@router.post(
    "/generate-api-spec/{epic_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate OpenAPI spec for an epic",
)
async def trigger_generate_api_spec(
    epic_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.epic import Epic as _Epic
    from sqlalchemy import select as _sa_select
    try:
        _epic_uuid = uuid.UUID(epic_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid epic_id")
    _epic_res = await db.execute(_sa_select(_Epic).where(_Epic.id == _epic_uuid))
    _epic = _epic_res.scalar_one_or_none()
    if not _epic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Epic not found.")
    await verify_project_access(db, project_id=str(_epic.project_id), user_id=str(current_user.id))
    task = generate_api_spec.delay(
        epic_id=epic_id,
        initiated_by=str(current_user.id),
    )
    return {"run_id": task.id, "epic_id": epic_id, "status": "queued"}


@router.post(
    "/generate-ui-spec/{epic_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate UI/UX specification for an epic",
)
async def trigger_generate_ui_spec(
    epic_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.epic import Epic as _Epic
    from sqlalchemy import select as _sa_select
    try:
        _epic_uuid = uuid.UUID(epic_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid epic_id")
    _epic_res = await db.execute(_sa_select(_Epic).where(_Epic.id == _epic_uuid))
    _epic = _epic_res.scalar_one_or_none()
    if not _epic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Epic not found.")
    await verify_project_access(db, project_id=str(_epic.project_id), user_id=str(current_user.id))
    task = generate_ui_spec.delay(
        epic_id=epic_id,
        initiated_by=str(current_user.id),
    )
    return {"run_id": task.id, "epic_id": epic_id, "status": "queued"}


@router.post(
    "/generate-release-notes/{sprint_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate release notes for a sprint",
)
async def trigger_generate_release_notes(
    sprint_id: str,
    audience: str = Query(default="technical", pattern="^(technical|business|public)$"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.sprint import Sprint as _Sprint
    from sqlalchemy import select as _sa_select
    try:
        _sprint_uuid = uuid.UUID(sprint_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid sprint_id")
    _sprint_res = await db.execute(_sa_select(_Sprint).where(_Sprint.id == _sprint_uuid))
    _sprint = _sprint_res.scalar_one_or_none()
    if not _sprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found.")
    await verify_project_access(db, project_id=str(_sprint.project_id), user_id=str(current_user.id))
    task = generate_release_notes.delay(
        sprint_id=sprint_id,
        audience=audience,
        initiated_by=str(current_user.id),
    )
    return {"run_id": task.id, "sprint_id": sprint_id, "status": "queued"}


# ── Generations List ───────────────────────────────────────────────────────────

@router.get(
    "/generations",
    summary="List AI generation runs",
)
async def list_generations(
    project_id: str | None = Query(default=None),
    workflow_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all AI generation runs with their status."""
    if project_id:
        await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    from app.services.ai_generation_service import AIGenerationService
    svc = AIGenerationService(db)
    return await svc.list_generations(
        user_id=str(current_user.id),
        project_id=project_id,
        workflow_type=workflow_type,
        status=status,
        page=page,
        page_size=page_size,
    )


# ── Prompt Templates ───────────────────────────────────────────────────────────

@router.post(
    "/prompts",
    status_code=status.HTTP_201_CREATED,
    summary="Create or update a prompt template",
)
async def save_prompt_template(
    payload: PromptTemplateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a custom prompt template for AI workflows."""
    from app.services.ai_generation_service import AIGenerationService
    svc = AIGenerationService(db)
    return await svc.save_prompt_template(
        **payload.model_dump(),
        created_by=str(current_user.id),
    )


@router.get(
    "/prompts",
    summary="List prompt templates",
)
async def list_prompt_templates(
    workflow_type: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List available AI prompt templates."""
    from app.services.ai_generation_service import AIGenerationService
    svc = AIGenerationService(db)
    return await svc.list_prompt_templates(
        workflow_type=workflow_type,
        is_active=is_active,
    )


@router.get(
    "/prompts/{prompt_id}",
    summary="Get prompt template",
)
async def get_prompt_template(
    prompt_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.ai_generation_service import AIGenerationService
    svc = AIGenerationService(db)
    prompt = await svc.get_prompt_template(prompt_id)
    if not prompt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found.")
    return prompt


@router.delete(
    "/prompts/{prompt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete prompt template",
)
async def delete_prompt_template(
    prompt_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.ai_generation_service import AIGenerationService
    svc = AIGenerationService(db)
    await svc.delete_prompt_template(prompt_id)
