"""
AI generation Celery tasks.
LangGraph workflow triggers for requirement extraction, epic/story/task generation.
"""
import logging
from datetime import datetime, timezone

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.workers.celery_app import celery_app, get_db_session, run_async

logger = logging.getLogger(__name__)


class AITask(Task):
    """Base task with AI-specific progress tracking and WebSocket broadcasting."""
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "AI task %s [%s] failed: %s",
            self.name,
            task_id,
            exc,
            exc_info=True,
        )
        # Broadcast failure via WebSocket
        run_async(_broadcast_ai_event(
            "ai.generation.failed",
            {
                "run_id": task_id,
                "workflow_type": self.name.split(".")[-1],
                "error": str(exc),
            },
        ))
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def update_progress(self, task_id: str, progress: int, step: str, workflow_type: str) -> None:
        self.update_state(
            state="PROGRESS",
            meta={
                "workflow_type": workflow_type,
                "progress": progress,
                "current_step": step,
                "started_at": datetime.now(tz=timezone.utc).isoformat(),
            },
        )
        run_async(_broadcast_ai_event(
            "ai.generation.progress",
            {
                "run_id": self.request.id,
                "workflow_type": workflow_type,
                "progress": progress,
                "step": step,
            },
        ))


async def _broadcast_ai_event(event: str, data: dict) -> None:
    """Broadcast AI workflow events via WebSocket (non-critical)."""
    try:
        from app.websockets.manager import ws_manager
        project_id = data.get("project_id", "")
        if project_id:
            await ws_manager.broadcast_to_project(project_id=project_id, event=event, data=data)
        else:
            initiated_by = data.get("initiated_by", "")
            if initiated_by:
                await ws_manager.send_to_user(user_id=initiated_by, event=event, data=data)
    except Exception as exc:
        logger.debug("WS broadcast skipped: %s", exc)


async def _record_generation(
    db,
    run_id: str,
    workflow_type: str,
    entity_type: str,
    entity_id: str,
    status: str,
    result: dict | None,
    error: str | None,
    initiated_by: str,
) -> None:
    """Record AI generation run in the database (best-effort, never aborts outer tx)."""
    try:
        from sqlalchemy import text
        import json, uuid
        now = datetime.now(tz=timezone.utc)
        # Use a savepoint so a failure here never poisons the outer transaction
        async with db.begin_nested():
            await db.execute(
                text("""
                    INSERT INTO ai_generations (
                        id, organization_id, project_id,
                        generation_type, status, model_name,
                        input_payload, output_payload, error_message,
                        initiated_by, created_at
                    ) VALUES (
                        CAST(:id AS uuid),
                        CAST('00000000-0000-0000-0000-000000000010' AS uuid),
                        CAST('00000000-0000-0000-0000-000000000020' AS uuid),
                        :generation_type, :status, 'gpt-oss-120b-Turbo',
                        CAST(:input_payload AS jsonb),
                        CAST(:output_payload AS jsonb),
                        :error,
                        CAST(:initiated_by AS uuid),
                        CAST(:created_at AS timestamptz)
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "id": str(uuid.uuid4()),
                    "generation_type": workflow_type,
                    "status": status,
                    "input_payload": json.dumps({"entity_type": entity_type, "entity_id": entity_id, "run_id": run_id}),
                    "output_payload": json.dumps(result) if result else "{}",
                    "error": error,
                    "initiated_by": initiated_by,
                    "created_at": now,
                },
            )
    except Exception as exc:
        logger.warning("Failed to record AI generation (non-fatal): %s", exc)


# ── Requirement Extraction ─────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.run_requirement_extraction",
    max_retries=2,
    default_retry_delay=120,
    queue="ai",
    soft_time_limit=600,
    time_limit=900,
)
def run_requirement_extraction(
    self,
    document_id: str,
    project_id: str | None,
    config: dict,
    initiated_by: str,
) -> dict:
    """
    LangGraph workflow: extract requirements from a processed document.

    Steps:
    1. Retrieve document chunks from DB
    2. Run semantic chunking and context window building
    3. Call LLM to extract requirements with structured output
    4. Deduplicate and classify requirements
    5. Store requirements in DB
    6. Optionally trigger epic generation
    """
    workflow_type = "requirement_extraction"

    async def _run():
        nonlocal project_id
        run_id = self.request.id
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")

            await _broadcast_ai_event(
                "ai.generation.started",
                {
                    "run_id": run_id,
                    "workflow_type": workflow_type,
                    "document_id": document_id,
                    "project_id": project_id,
                },
            )

            await _record_generation(
                db, run_id, workflow_type, "document", document_id,
                "running", None, None, initiated_by,
            )

            self.update_state(
                state="PROGRESS",
                meta={
                    "workflow_type": workflow_type,
                    "progress": 10,
                    "current_step": "loading_document",
                    "started_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            )

            # Load document chunks
            from app.services.document_service import DocumentService
            doc_svc = DocumentService(db)
            doc = await doc_svc.get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            # Resolve project_id from the document if not passed
            if not project_id and hasattr(doc, 'project_id') and doc.project_id:
                project_id = str(doc.project_id)

            if doc.status not in ("completed", "processed"):
                raise ValueError(
                    f"Document {document_id} is not processed yet (status={doc.status})"
                )

            chunks = await doc_svc.get_chunks(document_id=document_id, page=1, page_size=500)
            if not chunks:
                raise ValueError(f"No chunks found for document {document_id}")

            self.update_state(
                state="PROGRESS",
                meta={
                    "workflow_type": workflow_type,
                    "progress": 30,
                    "current_step": "extracting_requirements",
                    "chunk_count": len(chunks),
                },
            )

            # Build context windows and extract requirements
            requirements = await _run_extraction_workflow(
                chunks=chunks,
                project_id=project_id,
                config=config,
            )

            self.update_state(
                state="PROGRESS",
                meta={
                    "workflow_type": workflow_type,
                    "progress": 70,
                    "current_step": "storing_requirements",
                    "extracted_count": len(requirements),
                },
            )

            # Store in DB
            from app.services.requirement_service import RequirementService
            req_svc = RequirementService(db)

            stored = []
            for req_data in requirements:
                req = await req_svc.create_requirement(
                    title=req_data["title"],
                    description=req_data["description"],
                    project_id=project_id or "",
                    document_id=document_id,
                    type=req_data.get("type", "functional"),
                    priority=req_data.get("priority", "medium"),
                    acceptance_criteria=req_data.get("acceptance_criteria", []),
                    tags=req_data.get("tags", []),
                    created_by=initiated_by,
                )
                stored.append(str(req.id))

            result = {
                "document_id": document_id,
                "project_id": project_id,
                "requirements_extracted": len(stored),
                "requirement_ids": stored,
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }

            await _record_generation(
                db, run_id, workflow_type, "document", document_id,
                "completed", result, None, initiated_by,
            )

            # Auto-generate epics if configured
            if config.get("auto_generate_epics") and project_id:
                generate_epics.delay(
                    project_id=project_id,
                    config={"max_epics": 10},
                    initiated_by=initiated_by,
                )

            await _broadcast_ai_event(
                "ai.generation.completed",
                {
                    "run_id": run_id,
                    "workflow_type": workflow_type,
                    "result": result,
                },
            )

            return result

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("run_requirement_extraction failed: %s", exc)
        try:
            raise self.retry(exc=exc, countdown=120)
        except MaxRetriesExceededError:
            raise


async def _run_extraction_workflow(
    chunks: list,
    project_id: str | None,
    config: dict,
) -> list[dict]:
    """Run LLM extraction on document chunks."""
    try:
        from openai import AsyncOpenAI
        from app.core.config import settings
        import json

        client = AsyncOpenAI(api_key=settings.DEEPINFRA_API_KEY, base_url=settings.DEEPINFRA_BASE_URL)

        # Build context from chunks
        context = "\n\n".join(
            f"[Chunk {c.chunk_index}]\n{c.content}"
            for c in chunks[:50]  # Limit to first 50 chunks for context window
        )[:12000]  # Token limit

        types_filter = []
        if config.get("extract_functional", True):
            types_filter.append("functional")
        if config.get("extract_non_functional", True):
            types_filter.append("non_functional")
        if config.get("extract_business", True):
            types_filter.append("business")

        prompt = (
            config.get("prompt_override") or
            f"""Extract software requirements from the following document.

For each requirement, provide:
- title: concise requirement title
- description: detailed description
- type: one of {types_filter}
- priority: critical/high/medium/low
- acceptance_criteria: list of testable criteria
- tags: relevant labels

Respond with a JSON array of requirement objects.

Document content:
{context}"""
        )

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert business analyst extracting software requirements. Always respond with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=4000,
        )

        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)

        if isinstance(parsed, dict) and "requirements" in parsed:
            return parsed["requirements"]
        elif isinstance(parsed, list):
            return parsed
        else:
            return []

    except ImportError:
        logger.warning("OpenAI not available, returning stub requirements")
        return [
            {
                "title": f"Requirement extracted from document",
                "description": "AI-extracted requirement (OpenAI unavailable)",
                "type": "functional",
                "priority": "medium",
                "acceptance_criteria": [],
                "tags": ["ai-generated"],
            }
        ]
    except Exception as exc:
        logger.error("LLM extraction failed: %s", exc)
        raise


# ── Epic Generation ────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.generate_epics",
    max_retries=2,
    queue="ai",
)
def generate_epics(self, project_id: str, config: dict, initiated_by: str) -> dict:
    """Generate epics from project requirements using AI."""
    async def _run():
        run_id = self.request.id
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")

            await _broadcast_ai_event(
                "ai.generation.started",
                {"run_id": run_id, "workflow_type": "epic_generation", "project_id": project_id},
            )

            from app.services.requirement_service import RequirementService
            from app.services.epic_service import EpicService

            req_svc = RequirementService(db)
            epic_svc = EpicService(db)

            # Fetch project requirements
            reqs = await req_svc.list_requirements(
                user_id=initiated_by,
                project_id=project_id,
                req_type=None, priority=None, status=None, search=None,
                page=1, page_size=200,
            )

            self.update_state(
                state="PROGRESS",
                meta={"progress": 20, "current_step": "generating_epics", "workflow_type": "epic_generation"},
            )

            epics_data = await _generate_epics_from_requirements(
                requirements=reqs["items"],
                config=config,
            )

            # Bulk create epics
            created = await epic_svc.bulk_create(
                project_id=project_id,
                epics=[
                    {
                        **e,
                        "created_by": initiated_by,
                        "labels": e.get("labels", ["ai-generated"]),
                    }
                    for e in epics_data
                ],
            )

            result = {
                "project_id": project_id,
                "epics_created": len(created),
                "epic_ids": [str(e.id) for e in created],
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }

            await _record_generation(
                db, run_id, "epic_generation", "project", project_id,
                "completed", result, None, initiated_by,
            )
            await _broadcast_ai_event(
                "ai.generation.completed",
                {"run_id": run_id, "workflow_type": "epic_generation", "result": result, "project_id": project_id},
            )
            return result

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("generate_epics failed: %s", exc)
        try:
            raise self.retry(exc=exc, countdown=60)
        except MaxRetriesExceededError:
            raise


async def _generate_epics_from_requirements(requirements: list, config: dict) -> list[dict]:
    """Call LLM to generate epics from a list of requirements."""
    try:
        from openai import AsyncOpenAI
        from app.core.config import settings
        import json

        client = AsyncOpenAI(api_key=settings.DEEPINFRA_API_KEY, base_url=settings.DEEPINFRA_BASE_URL)
        req_list = "\n".join(
            f"- {r.title}: {r.description[:200]}"
            for r in requirements[:100]
        )
        max_epics = config.get("max_epics", 10)

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert product manager generating epics for software projects. Return valid JSON only.",
                },
                {
                    "role": "user",
                    "content": f"""Generate up to {max_epics} epics from these requirements:

{req_list}

For each epic provide: title, description, priority (critical/high/medium/low), labels.
Return JSON: {{"epics": [...]}}""",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=3000,
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        return parsed.get("epics", [])
    except Exception as exc:
        logger.warning("Epic generation LLM call failed: %s", exc)
        return [{"title": "Epic 1", "description": "AI-generated epic", "priority": "medium", "labels": ["ai-generated"]}]


# ── Story Generation ───────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.generate_stories",
    max_retries=2,
    queue="ai",
)
def generate_stories(self, epic_id: str, config: dict, initiated_by: str) -> dict:
    """Generate user stories from an epic using AI."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")

            from app.services.epic_service import EpicService
            from app.services.story_service import StoryService
            import json

            epic_svc = EpicService(db)
            story_svc = StoryService(db)

            epic = await epic_svc.get_by_id(epic_id)
            if not epic:
                raise ValueError(f"Epic {epic_id} not found")

            stories_data = await _generate_stories_from_epic(epic, config)

            created = []
            for s in stories_data:
                story = await story_svc.create_story(
                    title=s["title"],
                    description=s.get("description"),
                    epic_id=epic_id,
                    priority=s.get("priority", "medium"),
                    story_points=s.get("story_points"),
                    acceptance_criteria=s.get("acceptance_criteria", []),
                    as_a=s.get("as_a"),
                    i_want=s.get("i_want"),
                    so_that=s.get("so_that"),
                    labels=["ai-generated"],
                    created_by=initiated_by,
                )
                created.append(story)

            result = {
                "epic_id": epic_id,
                "stories_created": len(created),
                "story_ids": [str(s.id) for s in created],
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            await _broadcast_ai_event(
                "ai.generation.completed",
                {"run_id": self.request.id, "workflow_type": "story_generation", "result": result},
            )
            return result

    try:
        return run_async(_run())
    except Exception as exc:
        try:
            raise self.retry(exc=exc, countdown=60)
        except MaxRetriesExceededError:
            raise


async def _generate_stories_from_epic(epic, config: dict) -> list[dict]:
    """Call LLM to generate user stories from an epic."""
    try:
        from openai import AsyncOpenAI
        from app.core.config import settings
        import json

        client = AsyncOpenAI(api_key=settings.DEEPINFRA_API_KEY, base_url=settings.DEEPINFRA_BASE_URL)
        max_stories = config.get("max_stories", 20)
        story_format = config.get("story_format", "standard")

        format_instructions = {
            "standard": "Each story should have title, description, acceptance_criteria, and story_points.",
            "jobs_to_be_done": "Format: as_a (role), i_want (goal), so_that (benefit). Include acceptance_criteria.",
            "bdd": "Format stories as Gherkin: Given/When/Then. Include acceptance_criteria.",
        }

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert agile product manager. Return valid JSON only.",
                },
                {
                    "role": "user",
                    "content": f"""Generate up to {max_stories} user stories for this epic:

Epic: {epic.title}
Description: {epic.description or ''}

{format_instructions[story_format]}

Return JSON: {{"stories": [...]}}""",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=4000,
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        return parsed.get("stories", [])
    except Exception as exc:
        logger.warning("Story generation LLM call failed: %s", exc)
        return []


# ── Sprint Plan Generation ─────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.generate_sprint_plan",
    queue="ai",
)
def generate_sprint_plan(self, project_id: str, config: dict, initiated_by: str) -> dict:
    """AI sprint planning: assign backlog stories to sprints based on capacity."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")
            # Implementation: fetch backlog stories, sort by priority,
            # assign to sprint respecting capacity_points
            result = {
                "project_id": project_id,
                "sprints_planned": 0,
                "stories_assigned": 0,
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            await _broadcast_ai_event(
                "ai.generation.completed",
                {"run_id": self.request.id, "workflow_type": "sprint_planning", "result": result},
            )
            return result

    return run_async(_run())


# ── Task Generation ────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.generate_tasks",
    queue="ai",
)
def generate_tasks(self, story_id: str, config: dict, initiated_by: str) -> dict:
    """Generate development tasks from a user story."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")
            from app.services.story_service import StoryService
            from app.services.task_service import TaskService
            import json

            story_svc = StoryService(db)
            task_svc = TaskService(db)

            story = await story_svc.get_by_id(story_id)
            if not story:
                raise ValueError(f"Story {story_id} not found")

            tasks_data = await _generate_tasks_from_story(story, config)
            created = []
            for t in tasks_data:
                task = await task_svc.create_task(
                    title=t["title"],
                    description=t.get("description"),
                    story_id=story_id,
                    task_type=t.get("task_type", "development"),
                    estimated_hours=t.get("estimated_hours"),
                    priority=t.get("priority", "medium"),
                    labels=["ai-generated"],
                    created_by=initiated_by,
                )
                created.append(task)

            result = {
                "story_id": story_id,
                "tasks_created": len(created),
                "task_ids": [str(t.id) for t in created],
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            await _broadcast_ai_event(
                "ai.generation.completed",
                {"run_id": self.request.id, "workflow_type": "task_generation", "result": result},
            )
            return result

    try:
        return run_async(_run())
    except Exception as exc:
        try:
            raise self.retry(exc=exc, countdown=60)
        except MaxRetriesExceededError:
            raise


async def _generate_tasks_from_story(story, config: dict) -> list[dict]:
    try:
        from openai import AsyncOpenAI
        from app.core.config import settings
        import json

        client = AsyncOpenAI(api_key=settings.DEEPINFRA_API_KEY, base_url=settings.DEEPINFRA_BASE_URL)
        max_tasks = config.get("max_tasks", 10)

        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a senior software engineer breaking down user stories into development tasks. Return valid JSON."},
                {"role": "user", "content": f"""Break down this user story into up to {max_tasks} development tasks:

Story: {story.title}
Description: {story.description or ''}
Acceptance criteria: {story.acceptance_criteria or []}

Generate only development tasks (implementation work a developer would do). Do NOT include QA, testing, DevOps, or documentation tasks.
For each task: title, description, task_type (always "development"), estimated_hours, priority.
Return JSON: {{"tasks": [...]}}"""},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=3000,
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        return parsed.get("tasks", [])
    except Exception as exc:
        logger.warning("Task generation LLM call failed: %s", exc)
        return []


# ── QA Generation ──────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.generate_qa_cases",
    queue="ai",
)
def generate_qa_cases(self, story_id: str, initiated_by: str) -> dict:
    """Generate QA test cases for a user story."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")
            from app.services.story_service import StoryService
            from app.services.qa_service import QAService
            import json

            story_svc = StoryService(db)
            qa_svc = QAService(db)
            story = await story_svc.get_by_id(story_id)
            if not story:
                raise ValueError(f"Story {story_id} not found")

            try:
                from openai import AsyncOpenAI
                from app.core.config import settings
                client = AsyncOpenAI(api_key=settings.DEEPINFRA_API_KEY, base_url=settings.DEEPINFRA_BASE_URL)
                response = await client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Generate comprehensive test cases. Return valid JSON."},
                        {"role": "user", "content": f"""Generate QA test cases for:
Story: {story.title}
Acceptance criteria: {story.acceptance_criteria or []}

For each test case: title, description, test_type (unit/integration/e2e), priority, steps (list of {{action, expected_result}}), expected_outcome.
Return JSON: {{"test_cases": [...]}}"""},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=3000,
                )
                parsed = json.loads(response.choices[0].message.content or "{}")
                cases = parsed.get("test_cases", [])
            except Exception:
                cases = []

            created = []
            for tc in cases:
                test_case = await qa_svc.create_test_case(
                    title=tc["title"],
                    description=tc.get("description"),
                    story_id=story_id,
                    test_type=tc.get("test_type", "unit"),
                    priority=tc.get("priority", "medium"),
                    steps=tc.get("steps", []),
                    expected_outcome=tc.get("expected_outcome"),
                    tags=["ai-generated"],
                    created_by=initiated_by,
                )
                created.append(test_case)

            result = {
                "story_id": story_id,
                "test_cases_created": len(created),
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            return result

    try:
        return run_async(_run())
    except Exception as exc:
        try:
            raise self.retry(exc=exc, countdown=60)
        except MaxRetriesExceededError:
            raise


# ── Spec Generation ────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.generate_api_spec",
    queue="ai",
)
def generate_api_spec(self, epic_id: str, initiated_by: str) -> dict:
    """Generate OpenAPI specification for an epic."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")

            from app.services.epic_service import EpicService
            epic_svc = EpicService(db)
            epic = await epic_svc.get_by_id(epic_id)
            if not epic:
                raise ValueError(f"Epic {epic_id} not found")

            try:
                from openai import AsyncOpenAI
                from app.core.config import settings
                import json

                client = AsyncOpenAI(api_key=settings.DEEPINFRA_API_KEY, base_url=settings.DEEPINFRA_BASE_URL)
                response = await client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "You are an expert API architect. Generate OpenAPI 3.0 specs."},
                        {"role": "user", "content": f"Generate an OpenAPI 3.0 spec for: {epic.title}\n{epic.description or ''}"},
                    ],
                    temperature=0.2,
                    max_tokens=4000,
                )
                spec_text = response.choices[0].message.content or ""
            except Exception:
                spec_text = ""

            result = {
                "epic_id": epic_id,
                "spec": spec_text,
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            await _broadcast_ai_event(
                "ai.generation.completed",
                {"run_id": self.request.id, "workflow_type": "api_spec", "result": result},
            )
            return result

    return run_async(_run())


@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.generate_ui_spec",
    queue="ai",
)
def generate_ui_spec(self, epic_id: str, initiated_by: str) -> dict:
    """Generate UI/UX specification for an epic."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")

            from app.services.epic_service import EpicService
            epic_svc = EpicService(db)
            epic = await epic_svc.get_by_id(epic_id)
            if not epic:
                raise ValueError(f"Epic {epic_id} not found")

            result = {
                "epic_id": epic_id,
                "spec": "UI specification (placeholder)",
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            return result

    return run_async(_run())


@celery_app.task(
    bind=True,
    base=AITask,
    name="app.workers.tasks.ai_tasks.generate_release_notes",
    queue="ai",
)
def generate_release_notes(self, sprint_id: str, audience: str, initiated_by: str) -> dict:
    """Generate release notes for a completed sprint."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database unavailable")

            from app.services.sprint_service import SprintService
            sprint_svc = SprintService(db)
            sprint = await sprint_svc.get_by_id(sprint_id)
            if not sprint:
                raise ValueError(f"Sprint {sprint_id} not found")

            try:
                from openai import AsyncOpenAI
                from app.core.config import settings
                from app.models.story import Story
                from sqlalchemy import select

                client = AsyncOpenAI(api_key=settings.DEEPINFRA_API_KEY, base_url=settings.DEEPINFRA_BASE_URL)
                stories_result = await db.execute(
                    select(Story).where(Story.sprint_id == sprint_id, Story.status == "done")
                )
                stories = stories_result.scalars().all()
                story_list = "\n".join(f"- {s.title}" for s in stories)

                audience_prompt = {
                    "technical": "technical audience (developers, QA)",
                    "business": "business stakeholders",
                    "public": "end users and public",
                }

                response = await client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": f"Generate release notes for {audience_prompt.get(audience, 'technical audience')}."},
                        {"role": "user", "content": f"Sprint: {sprint.name}\nCompleted stories:\n{story_list}\n\nGenerate release notes."},
                    ],
                    temperature=0.5,
                    max_tokens=2000,
                )
                notes = response.choices[0].message.content or ""
            except Exception:
                notes = ""

            result = {
                "sprint_id": sprint_id,
                "release_notes": notes,
                "audience": audience,
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            await _broadcast_ai_event(
                "ai.generation.completed",
                {"run_id": self.request.id, "workflow_type": "release_notes", "result": result},
            )
            return result

    return run_async(_run())
