"""
User Story management API routes.
"""
import logging
import uuid as _uuid
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_project_access
from app.services.story_service import StoryService

logger = logging.getLogger(__name__)
router = APIRouter()


class StoryCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    epic_id: str | None = None          # optional — epics removed from workflow
    project_id: str | None = None       # optional — used when epic_id not provided
    sprint_id: str | None = None
    assignee_id: str | None = None
    priority: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    story_points: int | None = Field(default=None, ge=0, le=100)
    acceptance_criteria: list[str] | None = None
    labels: list[str] | None = None
    as_a: str | None = None
    i_want: str | None = None
    so_that: str | None = None


class StoryUpdateRequest(BaseModel):
    # snake_case fields (used internally / from API clients)
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    sprint_id: str | None = None
    assignee_id: str | None = None
    priority: str | None = None
    story_points: int | None = Field(default=None, ge=0, le=100)
    status: str | None = None
    acceptance_criteria: list[str] | None = None
    labels: list[str] | None = None
    as_a: str | None = None
    i_want: str | None = None
    so_that: str | None = None
    type: str | None = None

    # camelCase aliases – the React frontend sends these names
    asA: str | None = None
    iWant: str | None = None
    soThat: str | None = None
    acceptanceCriteria: list[str] | None = None
    points: int | None = Field(default=None, ge=0, le=100)
    sprintId: str | None = None
    epicId: str | None = None

    def to_db_fields(self) -> dict:
        """Return a dict of DB column names → values, resolving camelCase aliases."""
        d: dict = {}
        # title / description / status / priority / type
        if self.title is not None:             d["title"] = self.title
        if self.description is not None:       d["description"] = self.description
        if self.status is not None:            d["status"] = self.status
        if self.priority is not None:          d["priority"] = self.priority
        if self.type is not None:              pass  # no `type` column on UserStory

        # User-story format fields (accept both cases)
        as_a   = self.asA   or self.as_a
        i_want = self.iWant or self.i_want
        so_that= self.soThat or self.so_that
        if as_a   is not None: d["as_a"]   = as_a
        if i_want is not None: d["i_want"] = i_want
        if so_that is not None: d["so_that"] = so_that

        # story_points (accept both names)
        pts = self.points if self.points is not None else self.story_points
        if pts is not None: d["story_points"] = pts

        # acceptance_criteria: list → newline-joined text
        ac = self.acceptanceCriteria or self.acceptance_criteria
        if ac is not None:
            d["acceptance_criteria"] = "\n".join(str(a) for a in ac)

        # sprint / epic ids
        sprint = self.sprintId or self.sprint_id
        if sprint is not None: d["current_sprint_id"] = sprint
        epic = self.epicId
        if epic is not None: d["epic_id"] = epic

        return d


class SprintAssignRequest(BaseModel):
    sprint_id: str | None


class GenerateStoriesRequest(BaseModel):
    project_id: str
    requirement_ids: list[str] | None = None   # None = use all project reqs


class StoryResponse(BaseModel):
    id: str
    title: str
    description: str | None
    epic_id: str | None
    sprint_id: str | None
    assignee_id: str | None
    priority: str
    story_points: int | None
    status: str
    acceptance_criteria: list[str]
    labels: list[str]
    as_a: str | None
    i_want: str | None
    so_that: str | None
    task_count: int
    completed_task_count: int
    created_by: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ── LLM helpers (shared with epics generation) ──────────────────────────────

def _req_line(r) -> str:
    r_type = (
        str(r.get("r_type", "functional"))
        if isinstance(r, dict)
        else (
            str(r.requirement_type.value)
            if hasattr(r, "requirement_type") and hasattr(r.requirement_type, "value")
            else "functional"
        )
    )
    r_pri = (
        str(r.get("r_pri", "medium"))
        if isinstance(r, dict)
        else (
            str(r.priority.value)
            if hasattr(r, "priority") and hasattr(r.priority, "value")
            else "medium"
        )
    )
    req_num = r.get("req_number") if isinstance(r, dict) else (getattr(r, "req_number", None) or str(r.id)[:8])
    title   = r.get("title", "") if isinstance(r, dict) else (getattr(r, "title", "") or "")
    return f"- [{req_num}] ({r_type}, {r_pri}): {title}"


def _extract_json_array(text: str) -> list:
    """Extract a JSON array from LLM output, with partial-JSON recovery."""
    import json, re

    # 1. Prefer fenced code blocks
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Try the whole array as-is
    arr_match = re.search(r"\[.*\]", text, re.DOTALL)
    if arr_match:
        try:
            return json.loads(arr_match.group())
        except json.JSONDecodeError:
            # 3. Truncated JSON — salvage complete objects before the cut-off
            raw = arr_match.group()
            objects: list = []
            depth = 0
            start = None
            for idx, ch in enumerate(raw):
                if ch == "{":
                    if depth == 0:
                        start = idx
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start is not None:
                        try:
                            obj = json.loads(raw[start: idx + 1])
                            objects.append(obj)
                        except json.JSONDecodeError:
                            pass
                        start = None
            if objects:
                logger.warning(
                    "_extract_json_array: recovered %d complete objects from truncated JSON",
                    len(objects),
                )
                return objects

    # 4. Last resort: parse the raw text directly
    return json.loads(text)


async def _call_llm(client, model: str, system: str, user: str, max_tokens: int = 4000) -> str:
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.25,
    )
    content = resp.choices[0].message.content or ""
    if not content.strip() and resp.choices[0].finish_reason == "length":
        raise RuntimeError(
            f"LLM returned empty content with finish_reason=length "
            f"(used {resp.usage.completion_tokens} tokens). Increase max_tokens."
        )
    return content.strip()


def _serialize_story(s) -> dict:
    """Serialize a UserStory ORM object to a frontend-friendly dict."""
    def _str(v):
        return str(v) if v is not None else None

    priority_map = {90: "critical", 70: "high", 50: "medium", 20: "low"}
    priority_raw = s.priority
    if hasattr(priority_raw, "value"):
        priority_raw = priority_raw.value
    # If it's an integer priority, convert; otherwise use string directly
    if isinstance(priority_raw, int):
        priority_str = priority_map.get(priority_raw, "medium")
    else:
        priority_str = str(priority_raw) if priority_raw else "medium"

    status_raw = s.status
    if hasattr(status_raw, "value"):
        status_raw = status_raw.value
    status_str = str(status_raw) if status_raw else "backlog"

    ac = s.acceptance_criteria
    if isinstance(ac, str):
        ac = [line.strip() for line in ac.split("\n") if line.strip()]
    elif not isinstance(ac, list):
        ac = []

    return {
        "id":                str(s.id),
        # identifier / storyId — both emitted so old + new frontend code works
        "identifier":        s.story_number or "",
        "storyId":           s.story_number or "",
        "title":             s.title or "",
        "description":       s.description or "",
        "asA":               s.as_a,
        "iWant":             s.i_want,
        "soThat":            s.so_that,
        "status":            status_str,
        "priority":          priority_str,
        # storyPoints / points — both emitted
        "storyPoints":       s.story_points,
        "points":            s.story_points,
        "type":              "user_story",
        "epicId":            _str(s.epic_id),
        "sprintId":          _str(s.current_sprint_id),
        "tags":              s.tags or [],
        "isAiGenerated":     s.is_ai_generated,
        "requirementId":     _str(s.requirement_id),
        "acceptanceCriteria": ac,
        "createdAt":         s.created_at.isoformat() if s.created_at else None,
        "updatedAt":         s.updated_at.isoformat() if s.updated_at else None,
    }


# ── Generate stories from requirements (must be before /{story_id}) ─────────

@router.post(
    "/generate-from-requirements",
    summary="AI-generate user stories directly from requirements",
)
async def generate_stories_from_requirements(
    payload: GenerateStoriesRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    For each requirement (or a batch of them), call the LLM to generate
    1-3 concrete user stories in the 'As a … I want … So that …' format
    with acceptance criteria.  Stories are persisted without an epic_id.
    """
    from app.models.requirement import Requirement
    from app.models.project import Project
    from app.models.user_story import UserStory
    from app.core.config import settings

    STORIES_PER_REQ = 1      # 1 story per requirement keeps output size manageable
    BATCH_SIZE = 20           # requirements per LLM call (40 caused JSON truncation at 8k tokens)
    MAX_REQS = 400            # hard cap — covers up to 20 parallel batches of 20

    try:
        project_uuid = _uuid.UUID(payload.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    proj = await db.get(Project, project_uuid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    await verify_project_access(db, project_id=payload.project_id, user_id=str(current_user.id))

    req_query = (
        select(Requirement)
        .where(Requirement.project_id == project_uuid)
        .where(Requirement.deleted_at.is_(None))
        .order_by(Requirement.req_number)
    )
    if payload.requirement_ids:
        req_uuids = [_uuid.UUID(r) for r in payload.requirement_ids]
        req_query = req_query.where(Requirement.id.in_(req_uuids))

    result = await db.execute(req_query)
    all_reqs = result.scalars().all()

    if not all_reqs:
        raise HTTPException(
            status_code=400,
            detail="No requirements found for this project. Extract requirements first.",
        )

    # Snapshot to plain dicts (avoids async session issues)
    req_snapshots = []
    for r in all_reqs[:MAX_REQS]:
        tags: list[str] = r.tags or []
        is_consolidated = "consolidated" in tags
        merged_tag = next((t for t in tags if t.startswith("merged:")), None)
        merged_count = int(merged_tag.split(":")[1]) if merged_tag else None
        group_tag = next((t for t in tags if t.startswith("group:")), None)
        group_topic = group_tag[6:] if group_tag else None  # remove "group:" prefix

        req_snapshots.append({
            "id":                  str(r.id),
            "req_number":          r.req_number or str(r.id)[:8],
            "title":               r.title or "",
            # Full description — consolidated reqs have long user-story descriptions
            "description":         r.description or "",
            # Full acceptance criteria — critical for consolidated reqs
            "acceptance_criteria": r.acceptance_criteria or "",
            "r_type":              (
                str(r.requirement_type.value)
                if hasattr(r.requirement_type, "value")
                else str(r.requirement_type or "functional")
            ),
            "r_pri":               (
                str(r.priority.value)
                if hasattr(r.priority, "value")
                else str(r.priority or "medium")
            ),
            "is_consolidated":     is_consolidated,
            "merged_count":        merged_count,   # how many original reqs were merged
            "group_topic":         group_topic,    # feature group topic (e.g. "Login Authentication")
        })

    # ── Build group → E# mapping ─────────────────────────────────────────────
    # Requirements with group: tags get E#-US# story IDs; others get plain US-N
    group_order: list[str] = []        # ordered list of unique group topics
    req_num_to_group: dict[str, str] = {}  # req_number → group topic

    for rs in req_snapshots:
        topic = rs.get("group_topic")
        if topic:
            req_num_to_group[rs["req_number"]] = topic
            if topic not in group_order:
                group_order.append(topic)

    # E1 = first group, E2 = second, etc.
    group_to_epic_num: dict[str, int] = {t: i + 1 for i, t in enumerate(group_order)}
    logger.info(
        "Story generation: %d epic groups detected: %s",
        len(group_order),
        ", ".join(f"E{v}={k}" for k, v in group_to_epic_num.items()),
    )

    chunks = [
        req_snapshots[i: i + BATCH_SIZE]
        for i in range(0, len(req_snapshots), BATCH_SIZE)
    ]
    logger.info(
        "Story generation: %d requirements → %d batches for project %s",
        len(req_snapshots), len(chunks), project_uuid,
    )

    all_story_dicts: list[dict] = []

    try:
        import asyncio as _asyncio
        from openai import AsyncOpenAI
        model: str = getattr(settings, "LLM_MODEL", "openai/gpt-oss-120b-Turbo")

        def _make_client():
            return AsyncOpenAI(
                api_key=settings.DEEPINFRA_API_KEY,
                base_url=settings.DEEPINFRA_BASE_URL,
            )

        # ── Each batch is one independent LLM call; run ALL in parallel ──────
        def _format_req_block(i: int, r: dict) -> str:
            """
            Build a rich requirement block for the LLM prompt.
            Consolidated requirements (merged from N originals) get extra context
            so the LLM knows it must cover all N sub-requirements.
            """
            header = (
                f"### REQ {i+1}: [{r['req_number']}]  "
                f"type={r['r_type']}  priority={r['r_pri']}"
            )
            if r["is_consolidated"] and r["merged_count"]:
                header += (
                    f"  ⚑ CONSOLIDATED — represents {r['merged_count']} original requirements"
                )

            parts = [header, f"Title: {r['title']}"]

            if r["description"]:
                parts.append(f"Description:\n{r['description']}")

            if r["acceptance_criteria"]:
                parts.append(f"Existing Acceptance Criteria (use ALL of these):\n{r['acceptance_criteria']}")

            return "\n".join(parts)

        async def _process_batch(batch_idx: int, batch: list) -> list[dict]:
            req_blocks = "\n\n".join(_format_req_block(i, r) for i, r in enumerate(batch))

            # Calculate how many AC items each story should have.
            # For consolidated reqs we keep ALL existing criteria and allow up to 10.
            # For single reqs we require 3–5.
            ac_rule = (
                "- acceptance_criteria: include EVERY criterion from 'Existing Acceptance Criteria' "
                "  verbatim, plus add any missing edge cases. Minimum 3, no upper limit — "
                "  a consolidated requirement must have ALL its criteria represented.\n"
                "  For requirements WITHOUT existing criteria: write exactly 3-5 criteria."
            )

            user_msg = f"""You are a senior Agile product owner writing detailed, production-ready user stories.

REQUIREMENTS (batch {batch_idx} of {len(chunks)}):
{req_blocks}

For EACH requirement above write exactly 1 user story. The story MUST capture EVERY detail in the requirement.

RULES:
- title: action-oriented, specific (max 80 chars). NOT a copy of the requirement title — reword as a story.
- as_a: specific user persona (e.g. "authenticated user", "project admin", "API consumer").
- i_want: the complete capability — cover ALL sub-requirements if this is a consolidated requirement.
  Do NOT omit any functionality described in the requirement.
- so_that: the concrete business value delivered.
{ac_rule}
  Format for every criterion (strict):
  "Given [specific precondition], When [specific action/trigger], Then [specific measurable outcome]"
  Each criterion must be independently testable. Be specific — include field names, values, error messages.
- priority: critical | high | medium | low  (use the requirement's priority)
- story_points: Fibonacci (1, 2, 3, 5, 8, 13) — consolidated stories covering 7+ requirements should be 8 or 13.
- requirement_number: exactly as shown (e.g. "REQ-001").

⚠ For CONSOLIDATED requirements (marked with ⚑):
  The story represents multiple original requirements merged together.
  The i_want MUST be a comprehensive sentence covering ALL aspects.
  Include ALL the given acceptance criteria — do not drop any.
  Use story_points 8 or 13 to reflect higher complexity.

Return ONLY a valid JSON array — no markdown, no explanation:
[
  {{
    "title": "Manage user authentication end-to-end",
    "as_a": "registered user",
    "i_want": "to securely log in with email/password, reset my password via email, and have my session expire after inactivity, so that my account stays secure and I can always regain access",
    "so_that": "my account is protected and I can always regain access without contacting support",
    "acceptance_criteria": [
      "Given a registered user on the login page, When they enter valid credentials and click Login, Then they are redirected to their dashboard and a session token is issued",
      "Given a user enters an incorrect password 5 times, When the 5th failed attempt occurs, Then the account is locked for 15 minutes and a notification email is sent",
      "Given a locked-out user clicks 'Forgot password', When they submit their email address, Then a reset link valid for 24 hours is sent to that address",
      "Given a user with an active session is idle for 30 minutes, When the inactivity threshold is reached, Then the session is invalidated and they are redirected to the login page"
    ],
    "priority": "high",
    "story_points": 8,
    "requirement_number": "REQ-001"
  }}
]"""
            try:
                client = _make_client()
                raw = await _call_llm(
                    client, model,
                    system=(
                        "You are a senior Agile product owner and QA lead. "
                        "Write detailed, production-ready user stories. "
                        "For consolidated requirements you MUST include every acceptance criterion provided — "
                        "never drop or summarise existing criteria. "
                        "Return only valid JSON — no markdown, no extra text."
                    ),
                    user=user_msg,
                    max_tokens=16000,
                )
                stories = _extract_json_array(raw)
                logger.info(
                    "  Batch %d/%d → %d stories generated",
                    batch_idx, len(chunks), len(stories),
                )
                return stories
            except Exception as batch_exc:
                logger.error(
                    "  Batch %d/%d failed (%s: %s)\n%s",
                    batch_idx, len(chunks), type(batch_exc).__name__, batch_exc,
                    traceback.format_exc(),
                )
                return []

        # Fire all batches simultaneously
        batch_results = await _asyncio.gather(
            *[_process_batch(idx + 1, batch) for idx, batch in enumerate(chunks)]
        )
        for result in batch_results:
            all_story_dicts.extend(result)

        logger.info(
            "Parallel generation complete: %d total stories from %d batches",
            len(all_story_dicts), len(chunks),
        )

    except Exception as exc:
        logger.error(
            "LLM story generation failed:\n%s", traceback.format_exc(),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Story generation failed: {exc}",
        )

    if not all_story_dicts:
        raise HTTPException(
            status_code=500,
            detail="LLM returned no stories. Please try again.",
        )

    # Build req_number → req_id / group map
    req_number_to_id: dict[str, str] = {r["req_number"]: r["id"] for r in req_snapshots}

    # Sort stories to keep group order stable (E1 stories before E2 etc.)
    req_num_order: dict[str, int] = {rs["req_number"]: idx for idx, rs in enumerate(req_snapshots)}

    def _sort_key(sd: dict) -> tuple:
        rn = sd.get("requirement_number", "")
        topic = req_num_to_group.get(rn, "")
        g_idx = group_order.index(topic) if topic in group_order else 99999
        r_idx = req_num_order.get(rn, 99999)
        return (g_idx, r_idx)

    all_story_dicts.sort(key=_sort_key)

    # Persist stories
    created: list = []
    priority_to_int = {"critical": 90, "high": 70, "medium": 50, "low": 20}

    # Get current plain-story count for fallback US-N numbering
    count_result = await db.execute(
        select(func.count()).select_from(UserStory).where(UserStory.project_id == project_uuid)
    )
    existing_count = count_result.scalar() or 0
    group_story_counters: dict[str, int] = {}  # epic_num → story counter within group
    plain_idx = 0                               # counter for ungrouped stories

    for i, sd in enumerate(all_story_dicts):
        # Determine story number (E#-US# or US-NNN)
        req_num = sd.get("requirement_number")
        topic = req_num_to_group.get(req_num, "") if req_num else ""

        if topic and topic in group_to_epic_num:
            epic_num = group_to_epic_num[topic]
            group_story_counters[epic_num] = group_story_counters.get(epic_num, 0) + 1
            us_num = group_story_counters[epic_num]
            story_number = f"E{epic_num}-US{us_num}"
            story_tags = ["ai-generated", f"epic:E{epic_num}", f"epic-topic:{topic}"]
        else:
            plain_idx += 1
            story_number = f"US-{existing_count + plain_idx:03d}"
            story_tags = ["ai-generated"]

        pri_str = str(sd.get("priority", "medium")).lower()
        if pri_str not in priority_to_int:
            pri_str = "medium"

        # acceptance_criteria: LLM returns list[str] or newline-joined string
        ac_raw = sd.get("acceptance_criteria") or []
        if isinstance(ac_raw, list):
            ac_text = "\n".join(str(a) for a in ac_raw)
        else:
            ac_text = str(ac_raw)

        req_id = None
        if req_num and req_num in req_number_to_id:
            try:
                req_id = _uuid.UUID(req_number_to_id[req_num])
            except ValueError:
                pass

        story = UserStory(
            id=_uuid.uuid4(),
            project_id=project_uuid,
            organization_id=proj.organization_id,
            story_number=story_number,
            title=str(sd.get("title", f"Story {i+1}"))[:500],
            description=None,
            as_a=sd.get("as_a"),
            i_want=sd.get("i_want"),
            so_that=sd.get("so_that"),
            acceptance_criteria=ac_text,
            status="backlog",
            priority=pri_str,
            story_points=sd.get("story_points"),
            is_ai_generated=True,
            tags=story_tags,
            requirement_id=req_id,
            epic_id=None,
            created_by=current_user.id,
            updated_by=current_user.id,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        db.add(story)
        created.append(story)

    await db.commit()

    serialized = []
    for s in created:
        await db.refresh(s)
        serialized.append(_serialize_story(s))

    logger.info(
        "Story generation complete: %d stories persisted for project %s",
        len(serialized), project_uuid,
    )
    return {
        "stories":           serialized,
        "count":             len(serialized),
        "requirements_used": len(req_snapshots),
        "batches_processed": len(chunks),
    }


@router.delete(
    "",
    status_code=status.HTTP_200_OK,
    summary="Delete all stories for a project",
)
async def clear_all_stories(
    project_id: str = Query(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete all stories for the given project_id."""
    from app.models.user_story import UserStory
    from sqlalchemy import update as sql_update

    try:
        project_uuid = _uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))

    result = await db.execute(
        sql_update(UserStory)
        .where(UserStory.project_id == project_uuid)
        .where(UserStory.deleted_at.is_(None))
        .values(deleted_at=datetime.now(tz=timezone.utc))
        .returning(UserStory.id)
    )
    deleted_ids = result.scalars().all()
    await db.commit()
    return {"deleted": len(deleted_ids)}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create user story",
)
async def create_story(
    payload: StoryCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user_story import UserStory

    # Resolve project_id from epic or direct field
    project_uuid: _uuid.UUID | None = None
    if payload.project_id:
        try:
            project_uuid = _uuid.UUID(payload.project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project_id")

    if project_uuid is None:
        raise HTTPException(status_code=400, detail="project_id is required")

    # Get org_id from project
    from app.models.project import Project
    proj = await db.get(Project, project_uuid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    await verify_project_access(db, project_id=str(project_uuid), user_id=str(current_user.id))

    # Determine next story number
    count_result = await db.execute(
        select(func.count()).select_from(UserStory).where(UserStory.project_id == project_uuid)
    )
    existing_count = count_result.scalar() or 0
    story_number = f"US-{existing_count + 1:03d}"

    # Convert acceptance_criteria list to text
    ac_text: str | None = None
    if payload.acceptance_criteria:
        ac_text = "\n".join(payload.acceptance_criteria)

    story = UserStory(
        id=_uuid.uuid4(),
        project_id=project_uuid,
        organization_id=proj.organization_id,
        story_number=story_number,
        title=payload.title,
        description=payload.description,
        as_a=payload.as_a,
        i_want=payload.i_want,
        so_that=payload.so_that,
        acceptance_criteria=ac_text,
        status="backlog",
        priority=payload.priority or "medium",
        story_points=payload.story_points,
        is_ai_generated=False,
        epic_id=_uuid.UUID(payload.epic_id) if payload.epic_id else None,
        current_sprint_id=_uuid.UUID(payload.sprint_id) if payload.sprint_id else None,
        created_by=current_user.id,
        updated_by=current_user.id,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    return _serialize_story(story)


@router.get(
    "",
    summary="List user stories",
)
async def list_stories(
    project_id: str | None = Query(default=None),
    epic_id: str | None = Query(default=None),
    sprint_id: str | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=500, ge=1, le=500),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user_story import UserStory

    query = select(UserStory).where(UserStory.deleted_at.is_(None))
    if project_id:
        try:
            project_uuid = _uuid.UUID(project_id)
            query = query.where(UserStory.project_id == project_uuid)
        except ValueError:
            pass
        else:
            await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    if epic_id:
        query = query.where(UserStory.epic_id == _uuid.UUID(epic_id))
    if sprint_id:
        query = query.where(UserStory.current_sprint_id == _uuid.UUID(sprint_id))
    if assignee_id:
        query = query.where(UserStory.created_by == _uuid.UUID(assignee_id))
    if status:
        query = query.where(UserStory.status == status)
    if priority:
        query = query.where(UserStory.priority == priority)

    total_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(total_q)).scalar() or 0
    items = (
        await db.execute(
            query.order_by(UserStory.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return {
        "items": [_serialize_story(s) for s in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/{story_id}",
    summary="Get story details",
)
async def get_story(
    story_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user_story import UserStory
    try:
        story_uuid = _uuid.UUID(story_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid story_id")
    story = await db.get(UserStory, story_uuid)
    if not story or story.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")
    await verify_project_access(db, project_id=str(story.project_id), user_id=str(current_user.id))
    return _serialize_story(story)




@router.patch(
    "/bulk-status",
    summary="Bulk update story statuses in one request",
)
async def bulk_update_story_status(
    payload: dict,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update status for multiple stories in a single DB round-trip."""
    from app.models.user_story import UserStory
    from sqlalchemy import update as sa_update
    import uuid as _uuid

    ids: list[str] = payload.get("ids", [])
    new_status: str = payload.get("status", "")
    if not ids or not new_status:
        raise HTTPException(status_code=400, detail="ids and status are required")

    try:
        uuids = [_uuid.UUID(i) for i in ids]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story id in list")

    await db.execute(
        sa_update(UserStory)
        .where(UserStory.id.in_(uuids))
        .values(status=new_status)
    )
    await db.commit()
    return {"updated": len(uuids), "status": new_status}

@router.patch(
    "/{story_id}",
    summary="Update user story",
)
async def update_story(
    story_id: str,
    payload: StoryUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user_story import UserStory
    from sqlalchemy import update as sql_update

    try:
        story_uuid = _uuid.UUID(story_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid story_id")

    story = await db.get(UserStory, story_uuid)
    if not story or story.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")

    await verify_project_access(db, project_id=str(story.project_id), user_id=str(current_user.id))

    db_fields = payload.to_db_fields()
    if not db_fields:
        # Nothing to update — return current state
        return _serialize_story(story)

    db_fields["updated_at"] = datetime.now(tz=timezone.utc)

    await db.execute(
        sql_update(UserStory)
        .where(UserStory.id == story_uuid)
        .values(**db_fields)
    )
    await db.commit()
    await db.refresh(story)
    return _serialize_story(story)


@router.delete(
    "/{story_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user story",
)
async def delete_story(
    story_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user_story import UserStory
    from sqlalchemy import update as sql_update

    try:
        story_uuid = _uuid.UUID(story_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid story_id")

    story = await db.get(UserStory, story_uuid)
    if not story or story.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")

    await verify_project_access(db, project_id=str(story.project_id), user_id=str(current_user.id))

    await db.execute(
        sql_update(UserStory)
        .where(UserStory.id == story_uuid)
        .values(deleted_at=datetime.now(tz=timezone.utc))
    )
    await db.commit()


@router.patch(
    "/{story_id}/sprint",
    summary="Assign story to sprint",
)
async def assign_sprint(
    story_id: str,
    payload: SprintAssignRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign or unassign a story to/from a sprint."""
    from app.models.user_story import UserStory
    from sqlalchemy import update as sql_update

    try:
        story_uuid = _uuid.UUID(story_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid story_id")

    story = await db.get(UserStory, story_uuid)
    if not story or story.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")

    sprint_uuid = None
    if payload.sprint_id:
        try:
            sprint_uuid = _uuid.UUID(payload.sprint_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid sprint_id")

    await db.execute(
        sql_update(UserStory)
        .where(UserStory.id == story_uuid)
        .values(current_sprint_id=sprint_uuid, updated_at=datetime.now(tz=timezone.utc))
    )
    await db.commit()
    await db.refresh(story)
    return _serialize_story(story)


@router.get(
    "/{story_id}/tasks",
    summary="Get tasks for a story",
)
async def get_story_tasks(
    story_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = StoryService(db)
    story = await svc.get_by_id(story_id)
    if not story:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")
    return await svc.get_tasks(story_id=story_id)


class StoryTaskCreateRequest(BaseModel):
    """Accepts camelCase field names as sent by the frontend tasksApi.create()."""
    title: str = Field(min_length=1, max_length=500)
    # Frontend sends "type" (matches Task interface TaskType)
    type: str = Field(default="development", pattern="^(development|design|testing|documentation|research|bug|devops|feature)$")
    priority: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    # Frontend sends "estimatedHours"
    estimatedHours: float | None = Field(default=None, ge=0, le=999)
    # Frontend sends "assigneeId"
    assigneeId: str | None = None
    description: str | None = None


@router.post(
    "/{story_id}/tasks",
    status_code=status.HTTP_201_CREATED,
    summary="Create a task for a story",
)
async def create_story_task(
    story_id: str,
    payload: StoryTaskCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = StoryService(db)
    story = await svc.get_by_id(story_id)
    if not story:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found.")
    from app.services.task_service import TaskService
    task_svc = TaskService(db)
    return await task_svc.create_task(
        story_id=story_id,
        title=payload.title,
        task_type=payload.type,
        priority=payload.priority,
        estimated_hours=payload.estimatedHours,
        assignee_id=payload.assigneeId,
        description=payload.description,
        created_by=str(current_user.id),
    )


def _safe_parse_json(raw: str) -> dict:
    """Extract and parse the first JSON object from a string, with repair fallbacks."""
    import json as _j, re as _re
    # Locate outermost { ... }
    si, ei = raw.find("{"), raw.rfind("}")
    if si == -1 or ei <= si:
        return {"raw": raw[:500]}
    candidate = raw[si:ei + 1]
    # 1. Standard parse
    try:
        return _j.loads(candidate)
    except _j.JSONDecodeError:
        pass
    # 2. Strip trailing commas before ] or }  (common LLM mistake)
    repaired = _re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return _j.loads(repaired)
    except _j.JSONDecodeError:
        pass
    # 3. Replace single quotes with double quotes
    repaired2 = repaired.replace("'", '"')
    try:
        return _j.loads(repaired2)
    except _j.JSONDecodeError:
        pass
    # 4. Return whatever we have as raw text so the UI still renders
    return {"raw": candidate[:2000], "parse_error": "LLM returned malformed JSON"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /{story_id}/generate-tests  — 3-Brain AI Test Generation
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{story_id}/generate-tests",
    summary="Generate tests for a story using 3-Brain AI engine",
)
async def generate_tests_for_story(
    story_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import asyncio, json as _json, uuid as _uuid
    from sqlalchemy.orm import selectinload

    # ── 1. Gather context ────────────────────────────────────────────────────
    try:
        s_uuid = _uuid.UUID(story_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid story_id")

    from app.models.user_story import UserStory
    from app.models.task import Task
    from app.models.requirement import Requirement
    from app.models.sprint import Sprint

    story = await db.get(UserStory, s_uuid)
    if not story or story.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Story not found.")

    # Fetch tasks for this story
    tasks_result = await db.execute(
        select(Task).where(Task.user_story_id == s_uuid, Task.deleted_at.is_(None))
    )
    tasks = tasks_result.scalars().all()

    # Fetch linked requirement
    requirement = None
    if story.requirement_id:
        requirement = await db.get(Requirement, story.requirement_id)

    # Fetch sprint
    sprint = None
    if story.current_sprint_id:
        sprint = await db.get(Sprint, story.current_sprint_id)

    # ── 2. Brain 1 — Knowledge Graph ────────────────────────────────────────
    nodes: list[dict] = []
    edges: list[dict] = []

    nodes.append({"id": "story", "type": "UserStory", "label": story.title or "", "data": {
        "status": str(story.status),
        "priority": str(story.priority),
        "story_points": story.story_points,
        "as_a": story.as_a or "",
        "i_want": story.i_want or "",
        "so_that": story.so_that or "",
        "acceptance_criteria": story.acceptance_criteria or "",
    }})

    if requirement:
        nodes.append({"id": "req", "type": "Requirement", "label": requirement.title or "",
                      "data": {"description": requirement.description or "",
                               "type": str(requirement.requirement_type),
                               "acceptance_criteria": requirement.acceptance_criteria or ""}})
        edges.append({"from": "story", "to": "req", "relation": "DERIVED_FROM"})

    if sprint:
        nodes.append({"id": "sprint", "type": "Sprint", "label": sprint.name or "",
                      "data": {"status": str(sprint.status), "goal": sprint.goal or ""}})
        edges.append({"from": "story", "to": "sprint", "relation": "PLANNED_IN"})

    for i, t in enumerate(tasks):
        nid = f"task_{i}"
        nodes.append({"id": nid, "type": "Task", "label": t.title or "",
                      "data": {"type": str(t.task_type), "status": str(t.status),
                               "description": t.description or ""}})
        edges.append({"from": "story", "to": nid, "relation": "HAS_TASK"})

    brain1 = {
        "nodes": nodes,
        "edges": edges,
        "summary": (
            "Knowledge graph built with {} nodes and {} edges. "
            "Story '{}' connects to {}{} task(s), and {}.".format(
                len(nodes), len(edges), story.title,
                "requirement '{}', ".format(requirement.title or "") if requirement else "",
                len(tasks),
                "sprint '{}'".format(sprint.name or "") if sprint else "no sprint",
            )
        ),
    }

    # ── 3. Comprehensive AI Analysis (QA-Intelligence format) ────────────────
    brain2 = {}
    try:
        from langchain_openai import ChatOpenAI
        from app.ai.config import AIConfig

        story_ctx = (
            f"Story: {story.title}\n"
            f"As a: {story.as_a or 'user'}\n"
            f"I want: {story.i_want or story.title}\n"
            f"So that: {story.so_that or ''}\n"
            f"Acceptance Criteria:\n{story.acceptance_criteria or 'Not specified'}\n"
            f"Tasks: {', '.join(t.title or '' for t in tasks) or 'None'}\n"
            f"Requirement: {(requirement.title + ' — ' + (requirement.description or '')) if requirement else 'None'}\n"
            f"Sprint: {(sprint.name + ' (goal: ' + (sprint.goal or 'none') + ')') if sprint else 'None'}"
        )

        llm = ChatOpenAI(
            model=AIConfig._LLM_MODEL,
            temperature=0.1,
            max_tokens=4096,
            api_key=AIConfig.DEEPINFRA_API_KEY,
            base_url=AIConfig.DEEPINFRA_BASE_URL,
            timeout=120,
            max_retries=0,
        )

        prompt = (
            "You are a senior QA architect. Analyse this user story and generate a comprehensive QA intelligence report.\n\n"
            f"=== USER STORY ===\n{story_ctx}\n\n"
            "Respond ONLY with a single valid JSON object (no markdown fences). Include ALL sections:\n"
            '{"feature_name":"short name","detected_module":"module","detected_priority":"high","overall_risk":"P2",'
            '"complexity_level":"MODERATE","feature_status":"existing","feature_status_reason":"reason",'
            '"feature_understanding":"2-3 paragraphs about the feature and what QA must focus on",'
            '"impacted_modules":[{"id":"MOD-01","name":"Module","impact_type":"DIRECT","criticality":4,"description":"why"}],'
            '"event_flow":[{"step":1,"layer":"UI","component":"Component","action":"action","data":"data","validation_point":"assert X"}],'
            '"risk_areas":[{"feature":"feat","module":"mod","risk_score":0.8,"priority":"P1","reasons":["r1"],"past_bug_count":0}],'
            '"heads_up_warnings":[{"warning":"warning text","recommendation":"do this","severity":"high"}],'
            '"test_scenarios":[{"id":"TC-FUNC-001","type":"functional","scenario_type":"functional","title":"title",'
            '"description":"desc","preconditions":["pre1"],"steps":["Step 1: do x"],"expected_result":"result",'
            '"risk_level":"high","traceability":"From AC"}],'
            '"gherkin_test_cases":[{"feature":"Feature","scenario_title":"Scenario","tags":["@smoke"],'
            '"given":["system ready"],"when":["user acts"],"then":["outcome"]}],'
            '"regression_suite":[{"test_case_name":"TC name","priority":"MUST-RUN","module":"Mod","reason":"why"}],'
            '"missing_coverage":[{"area":"Area","description":"not covered","recommendation":"how to cover"}],'
            '"api_event_validation":[{"endpoint":"/api/x","method":"POST","validations":["check 200"],"event_triggers":["event"],"db_impacts":["table updated"]}]}\n\n'
            "Generate at minimum: 3 impacted_modules, 5 event_flow steps, 2 risk_areas, 2 heads_up_warnings, "
            "8 test_scenarios (mix functional/edge/negative), 4 gherkin_test_cases, 4 regression_suite items, "
            "3 missing_coverage items, 2 api_event_validation entries."
        )

        resp = await asyncio.wait_for(llm.ainvoke(prompt), timeout=115)
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        brain3 = _safe_parse_json(raw)
        brain3["rag_chunks_used"] = 0

    except Exception as exc:
        brain3 = {"error": str(exc)}

    return {
        "story": {
            "id": str(story.id),
            "identifier": story.story_number,
            "title": story.title,
            "status": str(story.status),
            "priority": str(story.priority),
        },
        "brain1": brain1,
        "brain2": brain2,
        "brain3": brain3,
    }

