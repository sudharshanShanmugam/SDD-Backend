"""
Epic management API routes.
Fully self-contained – queries the DB directly like the requirements router.
"""
import logging
import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_project_access
from app.models.epic import Epic

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/llm-test", summary="Debug: verify LLM reachability from inside FastAPI")
async def llm_test(current_user=Depends(get_current_user)):
    """Hit this endpoint to check whether the LLM API is reachable from the running server."""
    import re, json
    from openai import AsyncOpenAI
    from app.core.config import settings

    try:
        client = AsyncOpenAI(
            api_key=settings.DEEPINFRA_API_KEY,
            base_url=settings.DEEPINFRA_BASE_URL,
        )
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": 'Return exactly: [{"ok": true}]'}],
            max_tokens=30,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        return {"status": "ok", "model": settings.LLM_MODEL, "response": raw}
    except Exception as exc:
        import traceback
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "error_msg": str(exc),
            "traceback": traceback.format_exc()[-800:],
        }

# ── Status mapping ──────────────────────────────────────────────────────────
# Frontend Kanban uses: backlog | in_progress | review | done
# DB stores:            draft   | active      | on_hold | completed | cancelled

FRONTEND_TO_DB_STATUS: dict[str, str] = {
    "backlog":     "draft",
    "in_progress": "active",
    "review":      "on_hold",
    "done":        "completed",
    # pass-through for raw DB values
    "draft":       "draft",
    "active":      "active",
    "on_hold":     "on_hold",
    "completed":   "completed",
    "cancelled":   "cancelled",
}

DB_TO_FRONTEND_STATUS: dict[str, str] = {
    "draft":     "backlog",
    "active":    "in_progress",
    "on_hold":   "review",
    "completed": "done",
    "cancelled": "done",
}

# Priority: DB stores as integer 0-100; frontend uses string labels
PRIORITY_STR_TO_INT: dict[str, int] = {
    "critical": 90,
    "high":     70,
    "medium":   50,
    "low":      20,
}

def _int_to_priority(val) -> str:
    if val is None:
        return "medium"
    try:
        n = int(val)
    except (TypeError, ValueError):
        return str(val)
    if n >= 80:
        return "critical"
    if n >= 60:
        return "high"
    if n >= 30:
        return "medium"
    return "low"


# ── Pydantic models ─────────────────────────────────────────────────────────

class EpicCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    project_id: str
    priority: str = "medium"
    status: str = "backlog"
    start_date: str | None = None
    target_date: str | None = None
    tags: list[str] | None = None


class EpicUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    priority: str | None = None
    status: str | None = None
    start_date: str | None = None
    target_date: str | None = None
    tags: list[str] | None = None


# ── Serializer ──────────────────────────────────────────────────────────────

def _serialize_epic(e, req_count: int = 0) -> dict:
    raw_status = (
        str(e.status.value) if hasattr(e.status, "value") else str(e.status or "draft")
    )
    return {
        "id": str(e.id),
        "epicId": e.epic_number or str(e.id),
        "title": e.title or "",
        "description": e.description or "",
        "status": DB_TO_FRONTEND_STATUS.get(raw_status, "backlog"),
        "priority": _int_to_priority(e.priority),
        "projectId": str(e.project_id),
        "tags": list(e.tags or []),
        "startDate": e.start_date,
        "endDate": e.target_date,
        "isAiGenerated": bool(getattr(e, "is_ai_generated", False)),
        "storyCount": 0,
        "completedStories": 0,
        "requirementCount": req_count,
        "createdAt": e.created_at.isoformat() if e.created_at else "",
        "updatedAt": e.updated_at.isoformat() if e.updated_at else "",
    }


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, summary="Create epic")
async def create_epic(
    payload: EpicCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        project_uuid = _uuid.UUID(payload.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    # Get org_id from project
    from app.models.project import Project
    proj = await db.get(Project, project_uuid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    await verify_project_access(db, project_id=payload.project_id, user_id=str(current_user.id))

    # Auto-number: EPIC-NNN
    count_result = await db.execute(
        select(func.count()).select_from(Epic).where(Epic.project_id == project_uuid)
    )
    count = count_result.scalar() or 0
    epic_number = f"EPIC-{count + 1:03d}"

    db_status = FRONTEND_TO_DB_STATUS.get(payload.status, "draft")

    epic = Epic(
        id=_uuid.uuid4(),
        project_id=project_uuid,
        organization_id=proj.organization_id,
        epic_number=epic_number,
        title=payload.title,
        description=payload.description,
        status=db_status,
        priority=PRIORITY_STR_TO_INT.get(payload.priority, 50),
        tags=payload.tags or [],
        start_date=payload.start_date,
        target_date=payload.target_date,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(epic)
    await db.commit()
    await db.refresh(epic)
    return _serialize_epic(epic)


@router.get("", summary="List epics")
async def list_epics(
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=500, ge=1, le=1000),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Epic).where(Epic.deleted_at.is_(None))

    if project_id:
        try:
            query = query.where(Epic.project_id == _uuid.UUID(project_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project_id")
        await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))

    if status_filter:
        db_status = FRONTEND_TO_DB_STATUS.get(status_filter, status_filter)
        query = query.where(Epic.status == db_status)

    # Total count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginated results
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    epics = result.scalars().all()

    # Batch-fetch requirement counts for all returned epics
    from app.models.epic import epic_requirements as epic_req_table
    epic_ids = [e.id for e in epics]
    req_counts: dict = {}
    if epic_ids:
        count_q = (
            select(epic_req_table.c.epic_id, func.count().label("cnt"))
            .where(epic_req_table.c.epic_id.in_(epic_ids))
            .group_by(epic_req_table.c.epic_id)
        )
        count_rows = (await db.execute(count_q)).all()
        req_counts = {row.epic_id: row.cnt for row in count_rows}

    return {
        "items": [_serialize_epic(e, req_counts.get(e.id, 0)) for e in epics],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/{epic_id}", summary="Update epic")
async def update_epic(
    epic_id: str,
    payload: EpicUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = _uuid.UUID(epic_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid epic ID")

    result = await db.execute(select(Epic).where(Epic.id == uid, Epic.deleted_at.is_(None)))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")

    await verify_project_access(db, project_id=str(epic.project_id), user_id=str(current_user.id))

    raw = payload.model_dump(exclude_none=True)

    if "status" in raw:
        raw["status"] = FRONTEND_TO_DB_STATUS.get(raw["status"], raw["status"])

    if "priority" in raw and isinstance(raw["priority"], str):
        raw["priority"] = PRIORITY_STR_TO_INT.get(raw["priority"], 50)

    raw["updated_by"] = current_user.id
    raw["updated_at"] = datetime.now(tz=timezone.utc)

    await db.execute(sql_update(Epic).where(Epic.id == uid).values(**raw))
    await db.commit()
    db.expire_all()

    result = await db.execute(select(Epic).where(Epic.id == uid))
    updated = result.scalar_one()
    return _serialize_epic(updated)


@router.put("/{epic_id}", summary="Replace epic (alias for PATCH)")
async def replace_epic(
    epic_id: str,
    payload: EpicUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """PUT alias so the frontend update() call (which uses PUT) works."""
    return await update_epic(epic_id, payload, current_user, db)


@router.delete("/{epic_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete epic")
async def delete_epic(
    epic_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = _uuid.UUID(epic_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid epic ID")

    result = await db.execute(select(Epic).where(Epic.id == uid, Epic.deleted_at.is_(None)))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")

    await verify_project_access(db, project_id=str(epic.project_id), user_id=str(current_user.id))

    await db.execute(
        sql_update(Epic)
        .where(Epic.id == uid)
        .values(deleted_at=datetime.now(tz=timezone.utc))
    )
    await db.commit()


@router.delete("", summary="Delete all epics for a project")
async def delete_all_epics(
    project_id: str = Query(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete all epics for a project in one call (used before regenerating)."""
    try:
        proj_uuid = _uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))

    result = await db.execute(
        sql_update(Epic)
        .where(Epic.project_id == proj_uuid)
        .where(Epic.deleted_at.is_(None))
        .values(deleted_at=datetime.now(tz=timezone.utc))
        .returning(Epic.id)
    )
    deleted_ids = result.fetchall()
    await db.commit()
    return {"deleted": len(deleted_ids)}


class GenerateEpicsRequest(BaseModel):
    project_id: str
    requirement_ids: list[str] | None = None   # optional filter; None = use all project reqs


# ── Multi-pass chunked epic generation helpers ───────────────────────────────

CHUNK_SIZE = 100          # requirements per LLM pass
MAX_CHUNKS = 10           # max passes → covers up to 1 000 requirements
MAX_FINAL_EPICS = 20      # cap on persisted epics


def _req_line(r) -> str:
    """Single formatted line for one requirement."""
    r_type = (
        str(r.requirement_type.value)
        if hasattr(r.requirement_type, "value")
        else str(r.requirement_type or "functional")
    )
    r_pri = (
        str(r.priority.value)
        if hasattr(r.priority, "value")
        else str(r.priority or "medium")
    )
    return f"- [{r.req_number or str(r.id)[:8]}] ({r_type}, {r_pri}): {r.title}"


def _extract_json_array(text: str) -> list:
    """Pull the first JSON array out of an LLM response."""
    import json, re
    # Try fenced code block first
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    # Then bare array
    arr = re.search(r"\[.*\]", text, re.DOTALL)
    if arr:
        return json.loads(arr.group())
    return json.loads(text)


async def _call_llm(client, model: str, system: str, user: str, max_tokens: int = 4000) -> str:
    """Single LLM call, returns raw content string.

    max_tokens defaults to 4 000 — required for reasoning models (e.g. gpt-oss-120b-Turbo)
    that consume hidden thinking tokens before writing visible output.  Values below ~3 000
    cause finish_reason='length' with an empty response body.
    """
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
            f"(used {resp.usage.completion_tokens} tokens). "
            f"Increase max_tokens."
        )
    return content.strip()


async def _phase1_extract_themes(client, model: str, chunk: list, chunk_idx: int) -> list[dict]:
    """
    Phase 1 — Given ~100 requirements, identify 3-6 feature themes.
    Returns list of {title, description, priority, req_refs}.
    """
    lines = "\n".join(_req_line(r) for r in chunk)
    user_msg = f"""You are analysing part {chunk_idx} of a larger requirements list.

REQUIREMENTS (chunk {chunk_idx}):
{lines}

Identify 3-6 distinct feature themes that group these requirements into cohesive epics.
Each theme should be a business-facing feature area (e.g. "Authentication & Security", "Payment Processing").

Return a JSON array:
[
  {{
    "title": "Theme title (max 60 chars)",
    "description": "1-2 sentence description of what this theme covers.",
    "priority": "high",
    "req_refs": ["REQ-001", "REQ-002"]
  }}
]

Return ONLY the JSON array."""

    raw = await _call_llm(
        client, model,
        system="You are an expert Agile coach. Identify epic themes from requirements.",
        user=user_msg,
    )
    return _extract_json_array(raw)


async def _phase2_merge_themes(client, model: str, all_themes: list[dict]) -> list[dict]:
    """
    Phase 2 — Merge overlapping themes from all chunks into final epics.
    Returns list of {title, description, priority, status}.
    """
    theme_lines = "\n".join(
        f"- {t.get('title', '?')}: {t.get('description', '')}"
        for t in all_themes
    )
    user_msg = f"""You received these epic theme suggestions from analysing different parts of a large requirements document:

{theme_lines}

Merge duplicate or overlapping themes into a clean final list of 10-20 distinct epics.
Rules:
- Combine themes that cover the same feature area (e.g. "User Login" + "Password Reset" → "Authentication & Account Management")
- Keep themes that cover genuinely distinct areas
- Priority: critical | high | medium | low  (based on how many themes merged into it)
- Status must be: backlog

Return a JSON array:
[
  {{
    "title": "Final epic title (max 60 chars)",
    "description": "Clear 1-2 sentence description of what this epic covers and its business value.",
    "priority": "high",
    "status": "backlog"
  }}
]

Return ONLY the JSON array."""

    raw = await _call_llm(
        client, model,
        system="You are an expert Agile coach. Merge epic theme suggestions into a clean final list.",
        user=user_msg,
    )
    return _extract_json_array(raw)


def _fallback_epics(requirements: list) -> list[dict]:
    """
    Fallback when the LLM is unavailable.
    Groups requirements by type and produces readable business-facing epic descriptions.
    """
    from collections import defaultdict
    by_type: dict = defaultdict(list)
    for r in requirements:
        r_type = (
            str(r.requirement_type.value)
            if hasattr(r.requirement_type, "value")
            else "functional"
        )
        by_type[r_type].append(r)

    type_meta = {
        "functional": {
            "title":       "Core Product Functionality",
            "description": (
                "Covers the primary features and workflows that users interact with directly. "
                "Delivering these epics enables the product to fulfil its core purpose and meet user expectations."
            ),
            "priority": "high",
            "tags":     ["core", "features", "ux"],
        },
        "non_functional": {
            "title":       "Quality, Performance & Reliability",
            "description": (
                "Addresses system performance, scalability, availability, and maintainability requirements. "
                "Meeting these standards ensures the product remains fast, stable, and trustworthy under real-world load."
            ),
            "priority": "high",
            "tags":     ["performance", "reliability", "quality"],
        },
        "business": {
            "title":       "Business Rules & Process Automation",
            "description": (
                "Implements the business logic, workflows, and rules that drive organisational operations. "
                "These capabilities reduce manual effort, improve accuracy, and align the system with business goals."
            ),
            "priority": "high",
            "tags":     ["business-logic", "automation", "workflow"],
        },
        "technical": {
            "title":       "Technical Infrastructure & Integrations",
            "description": (
                "Covers the underlying architecture, third-party integrations, and platform services the product depends on. "
                "A solid technical foundation reduces operational risk and enables future features to be built faster."
            ),
            "priority": "medium",
            "tags":     ["infrastructure", "integrations", "devops"],
        },
        "constraint": {
            "title":       "Compliance, Security & Constraints",
            "description": (
                "Captures legal, regulatory, security, and operational constraints the system must satisfy. "
                "Addressing these requirements protects the organisation from risk and ensures the product can be deployed and operated safely."
            ),
            "priority": "critical",
            "tags":     ["compliance", "security", "legal"],
        },
    }

    result = []
    for rtype, reqs in by_type.items():
        meta = type_meta.get(rtype, {
            "title":       rtype.replace("_", " ").title(),
            "description": (
                f"Groups {len(reqs)} requirements related to {rtype.replace('_', ' ')}. "
                "Review and refine this epic to reflect specific business outcomes."
            ),
            "priority": "medium",
            "tags":     [rtype.replace("_", "-")],
        })
        result.append({
            "title":       meta["title"],
            "description": meta["description"],
            "priority":    meta["priority"],
            "status":      "backlog",
            "tags":        meta["tags"],
        })
    return result


@router.post("/generate-from-requirements", summary="AI-generate epics from requirements (multi-pass)")
async def generate_epics_from_requirements(
    payload: GenerateEpicsRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Multi-pass chunked approach:
      Phase 1 — Split requirements into chunks of 100; call LLM sequentially
                 per chunk to extract 3-6 feature themes each.
      Phase 2 — Send ALL collected themes to a single LLM merge call to
                 deduplicate and produce 10-20 final clean epics.
      Phase 3 — Persist the final epics to the DB.

    Handles up to 1 000 requirements (10 chunks × 100 each).
    """
    import traceback
    from app.models.requirement import Requirement
    from app.models.project import Project
    from app.core.config import settings

    try:
        project_uuid = _uuid.UUID(payload.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    # ── 1. Load project & requirements ──────────────────────────────────────
    proj = await db.get(Project, project_uuid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    await verify_project_access(db, project_id=payload.project_id, user_id=str(current_user.id))

    req_query = (
        select(Requirement)
        .where(Requirement.project_id == project_uuid)
        .where(Requirement.deleted_at.is_(None))
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

    # ── 2. Snapshot ORM data into plain dicts (avoids async session issues) ──
    # SQLAlchemy ORM objects can't be reliably accessed after session boundaries.
    # Snapshot all needed fields up front as plain Python values.
    req_snapshots = []
    req_number_to_id: dict[str, str] = {}   # req_number → str(uuid) for linking later
    for r in all_reqs:
        req_num = r.req_number or str(r.id)[:8]
        req_number_to_id[req_num] = str(r.id)
        req_snapshots.append({
            "id":         str(r.id),
            "req_number": req_num,
            "title":      r.title or "",
            "r_type":     (
                str(r.requirement_type.value)
                if hasattr(r.requirement_type, "value")
                else str(r.requirement_type or "functional")
            ),
            "r_pri":      (
                str(r.priority.value)
                if hasattr(r.priority, "value")
                else str(r.priority or "medium")
            ),
        })

    # ── 3. Split into chunks of CHUNK_SIZE ───────────────────────────────────
    reqs_to_use = req_snapshots[: MAX_CHUNKS * CHUNK_SIZE]
    chunks = [
        reqs_to_use[i : i + CHUNK_SIZE]
        for i in range(0, len(reqs_to_use), CHUNK_SIZE)
    ]
    logger.info(
        "Epic generation: %d requirements → %d chunks for project %s",
        len(reqs_to_use), len(chunks), project_uuid,
    )

    epics_data: list[dict] = []

    try:
        from openai import AsyncOpenAI
        model: str = getattr(settings, "LLM_MODEL", "openai/gpt-oss-120b-Turbo")

        def _make_client():
            return AsyncOpenAI(
                api_key=settings.DEEPINFRA_API_KEY,
                base_url=settings.DEEPINFRA_BASE_URL,
            )

        # ── Phase 1 — sequential chunk processing ────────────────────────────
        # Each chunk yields 3-6 themes; each theme carries the exact req_numbers
        # that belong to it (LLM-assigned).  We store them as "_req_numbers".
        all_themes: list[dict] = []   # each item: {title, description, priority, tags, _req_numbers}

        for chunk_idx, chunk in enumerate(chunks, start=1):
            lines = "\n".join(
                f"- [{s['req_number']}] ({s['r_type']}, {s['r_pri']}): {s['title']}"
                for s in chunk
            )
            chunk_req_numbers = [s["req_number"] for s in chunk]

            user_msg = f"""You are a senior business analyst reviewing software requirements.
Identify 3-6 distinct EPIC themes from the list below and assign EVERY requirement to exactly one theme.

REQUIREMENTS (batch {chunk_idx} of {len(chunks)}):
{lines}

Rules:
- Epic titles must be business-facing (e.g. "Customer Onboarding", "Payment Processing", "Reporting & Analytics").
- Avoid developer jargon ("API layer", "DB schema", "microservice").
- Description: 2 plain-English sentences. Sentence 1 — scope. Sentence 2 — business value.
- Priority: critical | high | medium | low (by business impact).
- Tags: 1-3 lowercase keywords.
- req_refs: list EVERY requirement number from the batch that belongs to this theme.
  Every requirement in the batch must appear in exactly one theme's req_refs.

Return ONLY a JSON array — no markdown, no extra text:
[
  {{
    "title": "Business-facing epic name (max 55 chars)",
    "description": "Sentence about scope. Sentence about business value.",
    "priority": "high",
    "tags": ["tag1", "tag2"],
    "req_refs": ["REQ-001", "REQ-003", "REQ-007"]
  }}
]"""

            try:
                client = _make_client()
                raw = await _call_llm(
                    client, model,
                    system=(
                        "You are a senior business analyst and Agile coach. "
                        "Assign every requirement in the batch to exactly one epic theme. "
                        "Always return valid JSON only."
                    ),
                    user=user_msg,
                )
                themes = _extract_json_array(raw)

                # ── validate and normalise req_refs ──────────────────────────
                chunk_req_set = set(chunk_req_numbers)
                assigned: set[str] = set()
                for theme in themes:
                    raw_refs = theme.get("req_refs") or []
                    # Keep only refs that actually exist in this chunk
                    valid_refs = [r for r in raw_refs if r in chunk_req_set]
                    theme["_req_numbers"] = valid_refs
                    assigned.update(valid_refs)

                # Any reqs the LLM missed → assign to the first (largest) theme
                unassigned = [r for r in chunk_req_numbers if r not in assigned]
                if unassigned and themes:
                    # Add missed reqs to the theme that already has the most
                    biggest = max(themes, key=lambda t: len(t.get("_req_numbers", [])))
                    biggest["_req_numbers"].extend(unassigned)
                    logger.debug(
                        "  Chunk %d: %d unassigned reqs redistributed to '%s'",
                        chunk_idx, len(unassigned), biggest.get("title", "?"),
                    )

                all_themes.extend(themes)
                logger.info(
                    "  Chunk %d/%d → %d themes, %d reqs assigned",
                    chunk_idx, len(chunks), len(themes), len(assigned) + len(unassigned),
                )
            except Exception as chunk_exc:
                logger.warning(
                    "  Chunk %d/%d failed (%s: %s) — skipping",
                    chunk_idx, len(chunks),
                    type(chunk_exc).__name__, chunk_exc,
                )

        logger.info("Phase 1 complete: %d raw themes from %d chunks", len(all_themes), len(chunks))

        if not all_themes:
            raise ValueError("Phase 1 produced no themes — all LLM chunk calls failed")

        # Index themes by their order so Phase 2 can reference them by number
        # theme_req_index[i] = list of req_numbers for all_themes[i]
        theme_req_index: list[list[str]] = [
            t.get("_req_numbers", []) for t in all_themes
        ]

        # ── Phase 2 — merge / deduplicate into final epics ───────────────────
        if len(all_themes) <= 8:
            # Already compact — normalise and pass through directly
            epics_data = [
                {
                    "title":        t.get("title", "Epic"),
                    "description":  t.get("description", ""),
                    "priority":     t.get("priority", "medium"),
                    "status":       "backlog",
                    "tags":         t.get("tags", []),
                    "_req_numbers": t.get("_req_numbers", []),
                }
                for t in all_themes
            ]
            logger.info("Phase 2 skipped (%d themes — no merge needed)", len(all_themes))
        else:
            # Number the themes so the LLM can reference them by index in source_theme_indices
            numbered_lines = "\n".join(
                f"{i}. {t.get('title', '?')}: {t.get('description', '')}"
                for i, t in enumerate(all_themes)
            )
            merge_msg = f"""You are a senior business analyst consolidating epic themes from a large project.

Below are {len(all_themes)} numbered raw themes identified from different batches of requirements:

{numbered_lines}

Your job: produce a final clean list of 8-15 distinct epics for a business roadmap.

Rules:
1. MERGE similar/overlapping themes into one epic.
   Example: themes 0,3,7 all relate to authentication → merge into "Authentication & Identity Management"
2. KEEP themes that represent genuinely different business areas.
3. Each epic title must be concise, business-facing, max 55 chars.
4. Description: exactly 2 sentences — scope then business value. Plain English. No bullets, no HTML.
5. Priority: critical | high | medium | low (by business impact).
6. Tags: 1-4 lowercase keywords.
7. status: always "backlog".
8. source_theme_indices: list the INDEX NUMBERS (from the numbered list above) of every theme
   that was merged into this epic. EVERY theme index must appear in exactly one epic's
   source_theme_indices list. Do not omit any index.

Return ONLY a JSON array — no markdown fences, no extra text:
[
  {{
    "title": "Authentication & Identity Management",
    "description": "Covers user registration, login, password recovery, and role-based access. Ensures secure, frictionless access for all users, reducing support tickets and compliance risk.",
    "priority": "critical",
    "status": "backlog",
    "tags": ["auth", "security"],
    "source_theme_indices": [0, 3, 7]
  }}
]"""

            client = _make_client()
            raw = await _call_llm(
                client, model,
                system=(
                    "You are a senior business analyst. Merge epic themes into a final roadmap list. "
                    "Every source theme index MUST appear in exactly one epic's source_theme_indices. "
                    "Return only valid JSON."
                ),
                user=merge_msg,
                max_tokens=6000,
            )
            epics_data = _extract_json_array(raw)
            logger.info("Phase 2 complete: %d final epics after merge", len(epics_data))

            # ── Map requirements to final epics via source_theme_indices ──────
            # Each final epic lists which theme indices it absorbed → collect their req_numbers
            all_indices = set(range(len(all_themes)))
            used_indices: set[int] = set()

            for epic_d in epics_data:
                indices = epic_d.get("source_theme_indices") or []
                req_numbers: list[str] = []
                seen_reqs: set[str] = set()
                for idx in indices:
                    if isinstance(idx, int) and 0 <= idx < len(theme_req_index):
                        used_indices.add(idx)
                        for rn in theme_req_index[idx]:
                            if rn not in seen_reqs:
                                seen_reqs.add(rn)
                                req_numbers.append(rn)
                epic_d["_req_numbers"] = req_numbers

            # Any theme indices the LLM missed → append their reqs to the first epic
            missed_indices = all_indices - used_indices
            if missed_indices and epics_data:
                logger.warning(
                    "Phase 2: %d theme indices not referenced by LLM — appending reqs to first epic",
                    len(missed_indices),
                )
                extra_reqs: list[str] = []
                for idx in sorted(missed_indices):
                    extra_reqs.extend(theme_req_index[idx])
                existing = set(epics_data[0].get("_req_numbers", []))
                epics_data[0]["_req_numbers"] = (
                    epics_data[0].get("_req_numbers", [])
                    + [r for r in extra_reqs if r not in existing]
                )

    except Exception as exc:
        logger.error(
            "LLM epic generation failed — falling back to type-based grouping.\n%s",
            traceback.format_exc(),
        )
        epics_data = _fallback_epics(all_reqs)

    # ── 5. Persist final epics + link requirements ──────────────────────────
    from sqlalchemy import insert as sql_insert
    from app.models.epic import epic_requirements as epic_req_table

    created_epics: list[Epic] = []
    epic_req_links: list[dict] = []   # collected for bulk insert after commit

    for i, ed in enumerate(epics_data[:MAX_FINAL_EPICS]):
        count_result = await db.execute(
            select(func.count()).select_from(Epic).where(Epic.project_id == project_uuid)
        )
        existing_count = count_result.scalar() or 0
        epic_number = f"EPIC-{existing_count + 1:03d}"

        db_status   = FRONTEND_TO_DB_STATUS.get(ed.get("status", "backlog"), "draft")
        db_priority = PRIORITY_STR_TO_INT.get(ed.get("priority", "medium"), 50)

        # Tags: sanitise to list[str], max 5 items, each max 30 chars
        raw_tags = ed.get("tags", [])
        clean_tags = [str(t)[:30] for t in raw_tags if t][:5] if isinstance(raw_tags, list) else []

        epic_id = _uuid.uuid4()
        epic = Epic(
            id=epic_id,
            project_id=project_uuid,
            organization_id=proj.organization_id,
            epic_number=epic_number,
            title=str(ed.get("title", f"Epic {i + 1}"))[:500],
            description=str(ed.get("description", "")),
            status=db_status,
            priority=db_priority,
            tags=clean_tags,
            is_ai_generated=True,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(epic)
        await db.flush()
        created_epics.append(epic)

        # Collect requirement links for this epic
        req_numbers = ed.get("_req_numbers", [])
        for rn in req_numbers:
            req_uuid_str = req_number_to_id.get(rn)
            if req_uuid_str:
                epic_req_links.append({
                    "epic_id": epic_id,
                    "requirement_id": _uuid.UUID(req_uuid_str),
                })

    # Bulk-insert epic ↔ requirement links (ignore duplicates via ON CONFLICT DO NOTHING)
    if epic_req_links:
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(epic_req_table).values(epic_req_links).on_conflict_do_nothing()
            await db.execute(stmt)
            logger.info("Linked %d requirement(s) to epics", len(epic_req_links))
        except Exception as link_exc:
            logger.warning("Could not insert requirement links: %s", link_exc)

    await db.commit()

    serialized = []
    for e in created_epics:
        await db.refresh(e)
        serialized.append(_serialize_epic(e))

    logger.info(
        "Multi-pass generation complete: %d epics persisted for project %s (from %d requirements, %d chunks)",
        len(serialized), project_uuid, len(all_reqs), len(chunks),
    )
    return {
        "epics":            serialized,
        "count":            len(serialized),
        "requirements_used": len(reqs_to_use),
        "chunks_processed": len(chunks),
    }


@router.get("/{epic_id}", summary="Get epic details")
async def get_epic(
    epic_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = _uuid.UUID(epic_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid epic ID")

    result = await db.execute(select(Epic).where(Epic.id == uid, Epic.deleted_at.is_(None)))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")

    await verify_project_access(db, project_id=str(epic.project_id), user_id=str(current_user.id))

    from app.models.epic import epic_requirements as epic_req_table
    cnt_result = await db.execute(
        select(func.count()).select_from(epic_req_table).where(epic_req_table.c.epic_id == uid)
    )
    req_count = cnt_result.scalar() or 0
    return _serialize_epic(epic, req_count)


@router.get("/{epic_id}/requirements", summary="List requirements linked to an epic")
async def get_epic_requirements(
    epic_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns the requirements linked to this epic via the epic_requirements join table."""
    try:
        uid = _uuid.UUID(epic_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid epic ID")

    # Verify epic exists
    epic_exists = await db.execute(select(Epic.id).where(Epic.id == uid, Epic.deleted_at.is_(None)))
    if not epic_exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Epic not found")

    from app.models.epic import epic_requirements as epic_req_table
    from app.models.requirement import Requirement

    join_q = (
        select(Requirement)
        .join(epic_req_table, Requirement.id == epic_req_table.c.requirement_id)
        .where(epic_req_table.c.epic_id == uid)
        .where(Requirement.deleted_at.is_(None))
        .order_by(Requirement.req_number)
    )
    rows = (await db.execute(join_q)).scalars().all()

    def _ser_req(r) -> dict:
        r_type = str(r.requirement_type.value) if hasattr(r.requirement_type, "value") else str(r.requirement_type or "")
        r_pri  = str(r.priority.value) if hasattr(r.priority, "value") else str(r.priority or "medium")
        return {
            "id":           str(r.id),
            "reqNumber":    r.req_number or "",
            "title":        r.title or "",
            "description":  r.description or "",
            "type":         r_type,
            "priority":     r_pri,
            "status":       str(r.status.value) if hasattr(r.status, "value") else str(r.status or ""),
            "isAiGenerated": bool(getattr(r, "is_ai_generated", False)),
        }

    return {"items": [_ser_req(r) for r in rows], "total": len(rows)}
