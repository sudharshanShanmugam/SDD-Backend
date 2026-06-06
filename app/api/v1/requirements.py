"""
Requirements management API routes.
CRUD and AI extraction trigger.
"""
import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_project_access
from app.services.requirement_service import RequirementService

logger = logging.getLogger(__name__)
router = APIRouter()


class RequirementType(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    BUSINESS = "business"
    TECHNICAL = "technical"
    CONSTRAINT = "constraint"


class RequirementPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RequirementCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str
    project_id: str
    document_id: str | None = None
    type: RequirementType = RequirementType.FUNCTIONAL
    priority: RequirementPriority = RequirementPriority.MEDIUM
    source: str | None = None
    acceptance_criteria: list[str] | None = None
    tags: list[str] | None = None


class RequirementUpdateRequest(BaseModel):
    # Accept both camelCase (from frontend) and snake_case field names
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    type: RequirementType | None = None
    priority: RequirementPriority | None = None
    # Frontend sends a plain string; list[str] accepted for API-level callers
    acceptance_criteria: str | list[str] | None = None
    tags: list[str] | None = None
    status: str | None = None


class BulkStatusRequest(BaseModel):
    """Approve / reject / reset a list of requirements in one shot."""
    ids: list[str]
    status: str   # frontend status: draft | in_progress | approved | rejected


class RequirementResponse(BaseModel):
    id: str
    title: str
    description: str
    project_id: str
    document_id: str | None
    type: str
    priority: str
    status: str
    source: str | None
    acceptance_criteria: list[str]
    tags: list[str]
    epic_id: str | None
    created_by: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create requirement",
)
async def create_requirement(
    payload: RequirementCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await verify_project_access(db, project_id=payload.project_id, user_id=str(current_user.id))
    svc = RequirementService(db)
    req = await svc.create_requirement(
        **payload.model_dump(),
        created_by=str(current_user.id),
    )
    return _serialize_requirement(req)


def _serialize_requirement(r) -> dict:
    """Convert a Requirement ORM object to a frontend-friendly dict."""
    def _str(v):
        return str(v) if v is not None else None

    # Map backend status → frontend status
    status_map = {
        "pending": "draft",
        "in_review": "in_progress",
        "approved": "approved",
        "rejected": "rejected",
        "revision_requested": "draft",
        "cancelled": "draft",
    }
    raw_status = str(r.status.value) if hasattr(r.status, "value") else str(r.status or "pending")
    req_type = str(r.requirement_type.value) if hasattr(r.requirement_type, "value") else str(r.requirement_type or "functional")

    return {
        "id": _str(r.id),
        "reqId": r.req_number or _str(r.id),
        "title": r.title or "",
        "description": r.description or "",
        "type": req_type,
        "priority": str(r.priority.value) if hasattr(r.priority, "value") else str(r.priority or "medium"),
        "status": status_map.get(raw_status, "draft"),
        "confidence": float(r.confidence_score or 0),
        "source": _str(r.source_document_id),
        "tags": list(r.tags or []),
        "acceptanceCriteria": r.acceptance_criteria or "",
        "isAiGenerated": bool(r.is_ai_generated),
        "projectId": _str(r.project_id),
        "documentId": _str(r.source_document_id),
        "createdAt": r.created_at.isoformat() if r.created_at else "",
        "updatedAt": r.updated_at.isoformat() if r.updated_at else "",
    }


@router.get(
    "",
    summary="List requirements",
)
async def list_requirements(
    project_id: str | None = Query(default=None),
    type: RequirementType | None = Query(default=None),
    priority: RequirementPriority | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=500, ge=1, le=1000),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if project_id:
        await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))
    svc = RequirementService(db)
    result = await svc.list_requirements(
        user_id=str(current_user.id),
        project_id=project_id,
        req_type=type.value if type else None,
        priority=priority.value if priority else None,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_serialize_requirement(r) for r in result["items"]],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


@router.patch(
    "/bulk-status",
    summary="Bulk update requirement status",
)
async def bulk_update_status_endpoint(
    payload: BulkStatusRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the same status on every requirement ID in the list (single SQL UPDATE)."""
    from sqlalchemy import update as sql_update
    from app.models.requirement import Requirement
    from datetime import datetime, timezone
    import uuid as _uuid

    FRONTEND_TO_DB_STATUS = {
        "draft":       "pending",
        "in_progress": "in_review",
        "approved":    "approved",
        "rejected":    "rejected",
    }

    db_status = FRONTEND_TO_DB_STATUS.get(payload.status, payload.status)
    uuids = []
    for raw_id in payload.ids:
        try:
            uuids.append(_uuid.UUID(raw_id))
        except ValueError:
            pass

    if not uuids:
        return {"updated": 0}

    result = await db.execute(
        sql_update(Requirement)
        .where(Requirement.id.in_(uuids))
        .values(status=db_status, updated_at=datetime.now(tz=timezone.utc))
    )
    await db.commit()
    updated = result.rowcount
    logger.info("Bulk status update → %s for %d requirements", db_status, updated)
    return {"updated": updated}


@router.post(
    "/clear",
    summary="Soft-delete all requirements for a project",
)
async def clear_requirements(
    project_id: str = Query(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deletes every non-deleted requirement in the project."""
    import uuid as _uuid
    from datetime import datetime, timezone
    from sqlalchemy import select, update as sql_update
    from app.models.requirement import Requirement

    try:
        project_uuid = _uuid.UUID(project_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid project_id")

    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))

    now = datetime.now(tz=timezone.utc)
    result = await db.execute(
        sql_update(Requirement)
        .where(
            Requirement.project_id == project_uuid,
            Requirement.deleted_at.is_(None),   # only touch rows that aren't already soft-deleted
        )
        .values(deleted_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    deleted = result.rowcount
    logger.info("Cleared %d requirements for project %s", deleted, project_id)
    return {"deleted": deleted}


@router.post(
    "/consolidate",
    summary="AI-consolidate requirements (6–8 per group) into rich user-story requirements",
)
async def consolidate_requirements(
    project_id: str = Query(..., description="Project whose requirements to consolidate"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Two-pass AI consolidation that produces requirements ready for user-story generation.

    Pass 1 – Semantic Grouping
        LLM groups all requirements into clusters of 6-8 per group by feature domain.
        Every requirement is guaranteed to appear in exactly one group.

    Pass 2 – Rich Synthesis (batched, 8 groups per LLM call)
        LLM writes a single high-quality requirement per cluster:
          • Feature-level title (5–10 words)
          • User-story description: "As a [role], I want [action], so that [value]"
          • 4–6 Given/When/Then acceptance criteria — testable by QA
          • Correct type (functional/non_functional/business/constraint) and priority
        Originals are soft-deleted; the synthesized requirement carries
        tags=["consolidated","merged:<N>"] for the UI badge.
    """
    import json as _json
    import math as _math
    import uuid as _uuid
    from datetime import datetime, timezone
    from sqlalchemy import select, func, update as sql_update
    from app.models.requirement import Requirement
    from app.models.project import Project
    from langchain_openai import ChatOpenAI
    from app.ai.config import AIConfig

    # ── 1. Validate project ────────────────────────────────────────────────────
    try:
        project_uuid = _uuid.UUID(project_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid project_id")

    project = await db.get(Project, project_uuid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))

    # ── 2. Load all non-deleted, non-approved requirements ────────────────────
    result = await db.execute(
        select(Requirement).where(
            Requirement.project_id == project_uuid,
            Requirement.deleted_at.is_(None),
            Requirement.status.notin_(["approved"]),
        ).order_by(Requirement.created_at.asc())
    )
    reqs = list(result.scalars().all())

    if len(reqs) < 3:
        return {
            "original_count": len(reqs),
            "consolidated_count": len(reqs),
            "groups_created": 0,
            "skipped": len(reqs),
            "message": "Nothing to consolidate — need at least 3 non-approved requirements.",
        }

    # ── 3. Helper functions ───────────────────────────────────────────────────
    PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    VALID_PRIORITIES = {"critical", "high", "medium", "low"}
    VALID_TYPES = {"functional", "non_functional", "business", "constraint"}

    # Target group size for the grouping prompt
    TARGET_MIN = 6
    TARGET_MAX = 8
    SYNTH_BATCH = 8      # groups per synthesis LLM call — keeps output ≤ 4096 tokens
    # Chunk size for Pass-1 grouping.
    # 40 reqs × ~9 UUIDs/group × 36 chars/UUID ≈ 1 500 tokens output — safe under 4 096.
    # Larger batches risk truncated JSON when max_tokens is hit mid-response.
    GROUP_CHUNK = 40

    def _highest_priority(plist: list[str]) -> str:
        return min(plist, key=lambda p: PRIORITY_ORDER.get(p, 2), default="medium")

    def _most_common_type(tlist: list[str]) -> str:
        valid = [t for t in tlist if t in VALID_TYPES]
        return max(set(valid), key=valid.count) if valid else "functional"

    def _req_priority(r) -> str:
        return str(r.priority.value if hasattr(r.priority, "value") else r.priority)

    def _req_type(r) -> str:
        return str(r.requirement_type.value if hasattr(r.requirement_type, "value") else r.requirement_type)

    def _extract_text(msg) -> str:
        """
        Pull plain text from a LangChain message, handling both:
          • str content  (most models)
          • list-of-blocks  [{"type": "text", "text": "..."}, ...]  (multimodal / newer LC)
        Returns an empty string rather than Python repr on failure.
        """
        content = msg.content if hasattr(msg, "content") else msg
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text") or block.get("content") or "")
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return ""

    def _safe_json(raw: str) -> dict:
        """Extract and parse the outermost JSON object from raw LLM text."""
        si, ei = raw.find("{"), raw.rfind("}")
        if si == -1 or ei <= si:
            logger.error("LLM returned no JSON. Raw response (first 500 chars): %s", raw[:500])
            raise ValueError(f"LLM returned no JSON. Response was: {raw[:200]!r}")
        try:
            return _json.loads(raw[si:ei + 1])
        except _json.JSONDecodeError as exc:
            logger.error("LLM JSON parse error: %s\nRaw (first 500): %s", exc, raw[:500])
            raise

    # ── 4. Build data maps ────────────────────────────────────────────────────
    req_map = {str(r.id): r for r in reqs}

    # Grouping payload: title only keeps prompt small (200 reqs ≈ 3 000 tokens)
    grouping_list = [{"id": str(r.id), "title": r.title} for r in reqs]

    # Synthesis payload: full details (description capped at 250 chars to save tokens)
    req_detail_map = {
        str(r.id): {
            "title":               r.title,
            "description":         (r.description or "")[:250],
            "type":                _req_type(r),
            "priority":            _req_priority(r),
            "acceptance_criteria": (r.acceptance_criteria or "")[:150],
        }
        for r in reqs
    }

    # ── 5. LLM clients ────────────────────────────────────────────────────────
    # NOTE: response_format=json_object is intentionally NOT set here.
    # Not all DeepInfra models support it; unsupported models silently return ''
    # instead of raising an error. We enforce JSON via the prompt wording instead.

    # Pass 1: compact grouping — ~40 reqs per chunk → ~500 tokens output, well within 4096
    llm_group = ChatOpenAI(
        model=AIConfig._LLM_MODEL,
        temperature=0.1,
        max_tokens=4096,
        api_key=AIConfig.DEEPINFRA_API_KEY,
        base_url=AIConfig.DEEPINFRA_BASE_URL,
        timeout=120,
        max_retries=2,
    )
    # Pass 2: per-batch synthesis — 8 groups per call
    llm_synth = ChatOpenAI(
        model=AIConfig._LLM_MODEL,
        temperature=0.2,
        max_tokens=4096,
        api_key=AIConfig.DEEPINFRA_API_KEY,
        base_url=AIConfig.DEEPINFRA_BASE_URL,
        timeout=180,
        max_retries=2,
    )

    # ── 6. Pass 1 — Chunked semantic grouping ────────────────────────────────
    #
    # Why chunked?
    #   300 reqs → ~43 groups → ~15 000 chars of JSON output → exceeds max_tokens=4096.
    #   The model truncates mid-response, producing truncated or single-group JSON.
    #   Fix: split into chunks of GROUP_CHUNK=40, run in parallel, then merge same-topic
    #   groups from different chunks.

    import asyncio as _asyncio
    import re as _re
    from langchain_core.messages import SystemMessage, HumanMessage

    # System message used for every grouping call.
    # A dedicated system message is more reliable than burying instructions in a human turn.
    _GROUPING_SYSTEM = SystemMessage(content=(
        "You are a senior business analyst. "
        "Your ONLY job is to output valid JSON. "
        "Do NOT include any explanation, markdown fences, or extra text — just raw JSON."
    ))

    def _build_grouping_messages(items: list[dict]) -> list:
        n = len(items)
        target_groups = max(1, _math.ceil(n / 7))
        compact = _json.dumps(items, separators=(",", ":"))
        human_text = (
            f"Group these {n} requirements into semantic clusters by feature domain.\n\n"
            "RULES:\n"
            f"• EVERY id must appear in exactly one group ({n} in, {n} out).\n"
            f"• Target {TARGET_MIN}–{TARGET_MAX} requirements per group; "
            f"aim for ~{target_groups} groups.\n"
            "• Group by feature area (e.g. authentication, search, payments).\n"
            "• Split domains with more than {TARGET_MAX} requirements into named sub-groups.\n"
            "• topic: 2–6 word label — specific, no generic names.\n\n"
            f"Requirements:\n{compact}\n\n"
            "Output format (raw JSON only, no extra text):\n"
            '{"groups":[{"topic":"<2-6 word label>","req_ids":["<uuid>","<uuid>"]}]}'
        )
        return [_GROUPING_SYSTEM, HumanMessage(content=human_text)]

    # Fallback LLM: Llama 3.1 8B — used when the main model returns empty
    llm_group_fallback = ChatOpenAI(
        model=AIConfig._ENTITY_MODEL,
        temperature=0.1,
        max_tokens=4096,
        api_key=AIConfig.DEEPINFRA_API_KEY,
        base_url=AIConfig.DEEPINFRA_BASE_URL,
        timeout=90,
        max_retries=1,
    )

    async def _group_chunk(chunk: list[dict], chunk_idx: int, total: int) -> list[dict]:
        """Run grouping LLM on one chunk; return list of raw group dicts.

        Attempt order:
          1. Main model with system+human messages
          2. Main model retry after 2s back-off
          3. Fallback model (Llama 3.1 8B)
        """
        messages = _build_grouping_messages(chunk)
        models = [(llm_group, "main"), (llm_group, "main-retry"), (llm_group_fallback, "llama-fallback")]
        for attempt, (llm, label) in enumerate(models, start=1):
            if attempt == 2:
                await _asyncio.sleep(2)   # back-off before retry
            try:
                r = await llm.ainvoke(messages)
                raw = _extract_text(r)
                if not raw:
                    logger.error(
                        "LLM (%s) returned empty text for chunk %d/%d. "
                        "content_type=%s additional_kwargs=%s",
                        label, chunk_idx, total,
                        type(getattr(r, "content", None)).__name__,
                        getattr(r, "additional_kwargs", {}),
                    )
                    raise ValueError("empty response")
                parsed = _safe_json(raw)
                result = [
                    {**g, "req_ids": [rid for rid in g.get("req_ids", []) if rid in req_map]}
                    for g in parsed.get("groups", [])
                    if any(rid in req_map for rid in g.get("req_ids", []))
                ]
                logger.info(
                    "Pass-1 chunk %d/%d (%s): %d groups from %d reqs",
                    chunk_idx, total, label, len(result), len(chunk),
                )
                return result
            except Exception as exc:
                logger.warning(
                    "Pass-1 chunk %d/%d attempt %d (%s) failed: %s",
                    chunk_idx, total, attempt, label, exc,
                )
        return []

    # Split into chunks
    chunks = [
        grouping_list[i : i + GROUP_CHUNK]
        for i in range(0, len(grouping_list), GROUP_CHUNK)
    ]
    logger.info("Pass-1: %d requirements → %d chunks of ≤%d", len(reqs), len(chunks), GROUP_CHUNK)

    # Run all chunks in parallel
    chunk_results = await _asyncio.gather(*[
        _group_chunk(chunk, idx + 1, len(chunks))
        for idx, chunk in enumerate(chunks)
    ])

    # ── 6a. Merge groups across chunks by normalised topic name ──────────────
    #
    # Groups from different chunks that share the same feature area
    # (e.g. "User Authentication" and "User Auth") are merged.
    # After merging, groups larger than TARGET_MAX×2 are split into sub-groups.

    def _normalise_topic(t: str) -> str:
        """Lowercase, strip punctuation, collapse spaces for fuzzy topic matching."""
        t = t.lower().strip()
        t = _re.sub(r"[^a-z0-9 ]+", " ", t)
        t = _re.sub(r"\s+", " ", t).strip()
        # Drop trailing "(1)" "(2)" suffixes so sub-groups from a prior run still merge
        t = _re.sub(r"\s*\(\d+\)$", "", t)
        return t

    topic_buckets: dict[str, dict] = {}   # normalised_topic → {topic, req_ids}
    for chunk_result in chunk_results:
        for g in chunk_result:
            key = _normalise_topic(g.get("topic", ""))
            if not key:
                key = "general"
            if key not in topic_buckets:
                topic_buckets[key] = {"topic": g["topic"], "req_ids": []}
            topic_buckets[key]["req_ids"].extend(g["req_ids"])

    # Split oversize buckets into numbered sub-groups of TARGET_MAX
    raw_groups: list[dict] = []
    for bucket in topic_buckets.values():
        ids = bucket["req_ids"]
        if len(ids) <= TARGET_MAX * 2:
            raw_groups.append({"topic": bucket["topic"], "req_ids": ids})
        else:
            sub_size = TARGET_MAX
            for sub_i, start in enumerate(range(0, len(ids), sub_size)):
                raw_groups.append({
                    "topic": f"{bucket['topic']} ({sub_i + 1})",
                    "req_ids": ids[start : start + sub_size],
                })

    if not raw_groups:
        # ── Pure-Python fallback: group by requirement_type, then slice to TARGET_MAX ──
        # This path is taken when every LLM chunk returns an empty/invalid response.
        # The result is deterministic and always produces groups of 6-8.
        logger.warning(
            "All LLM chunks failed — falling back to heuristic grouping for %d requirements",
            len(reqs),
        )
        TYPE_LABELS = {
            "functional":     "Functional",
            "non_functional": "Non-Functional",
            "business":       "Business",
            "constraint":     "Constraint",
        }
        # Bucket requirements by their type
        type_buckets: dict[str, list[str]] = {}
        for r in reqs:
            rtype = str(r.requirement_type.value if hasattr(r.requirement_type, "value") else r.requirement_type)
            type_buckets.setdefault(rtype, []).append(str(r.id))

        fallback_groups: list[dict] = []
        for rtype, ids in type_buckets.items():
            label = TYPE_LABELS.get(rtype, rtype.replace("_", " ").title())
            # Sort IDs for determinism, then split into chunks of TARGET_MAX
            ids.sort()
            for sub_i, start in enumerate(range(0, len(ids), TARGET_MAX)):
                sub_ids = ids[start : start + TARGET_MAX]
                suffix = f" ({sub_i + 1})" if len(ids) > TARGET_MAX else ""
                fallback_groups.append({"topic": f"{label}{suffix}", "req_ids": sub_ids})

        raw_groups = fallback_groups

    if not raw_groups:
        # Absolute last resort — one group per requirement (no synthesis possible)
        return {
            "original_count": len(reqs),
            "consolidated_count": len(reqs),
            "groups_created": 0,
            "skipped": len(reqs),
            "message": "Grouping failed completely — no requirements could be grouped.",
        }

    # ── 6b. Deduplicate IDs across groups ─────────────────────────────────────
    seen_ids: set[str] = set()
    deduped_groups: list[dict] = []
    for g in raw_groups:
        unique_ids = [rid for rid in g["req_ids"] if rid not in seen_ids]
        seen_ids.update(unique_ids)
        if unique_ids:
            deduped_groups.append({**g, "req_ids": unique_ids})
    raw_groups = deduped_groups

    # ── 6c. Safety net: append any missed requirements ────────────────────────
    llm_grouped_ids: set[str] = {rid for g in raw_groups for rid in g["req_ids"]}
    ungrouped = [rid for rid in req_map if rid not in llm_grouped_ids]

    if ungrouped:
        logger.info("Pass-1 missed %d requirement(s) — distributing to smallest groups", len(ungrouped))
        if raw_groups:
            for rid in ungrouped:
                smallest = min(raw_groups, key=lambda g: len(g["req_ids"]))
                smallest["req_ids"].append(rid)
        else:
            raw_groups.append({"topic": "General Requirements", "req_ids": ungrouped})

    if not raw_groups:
        return {
            "original_count": len(reqs),
            "consolidated_count": len(reqs),
            "groups_created": 0,
            "skipped": len(reqs),
            "message": "Could not form any requirement groups.",
        }

    # Log group size distribution
    sizes = [len(g["req_ids"]) for g in raw_groups]
    covered = sum(sizes)
    logger.info(
        "Pass-1 complete: %d groups covering %d/%d requirements | sizes min=%d avg=%.1f max=%d",
        len(raw_groups), covered, len(reqs),
        min(sizes), sum(sizes) / len(sizes), max(sizes),
    )

    # ── 7. Build groups payload for synthesis ─────────────────────────────────
    groups_payload = []
    for i, g in enumerate(raw_groups):
        member_ids = [rid for rid in g.get("req_ids", []) if rid in req_map]
        groups_payload.append({
            "group_index":  i,
            "topic":        g["topic"],
            "requirements": [req_detail_map[mid] for mid in member_ids if mid in req_detail_map],
            "member_ids":   member_ids,
        })

    # ── 8. Pass 2 — Batched synthesis (SYNTH_BATCH groups per LLM call) ───────
    #
    # Sending ALL groups at once to a single 4 096-token call produces truncated JSON
    # when there are many groups (30 × 200 tokens/group ≈ 6 000 tokens needed).
    # Batching at SYNTH_BATCH groups keeps each call well within the token budget.
    _SYNTH_SYSTEM = SystemMessage(content=(
        "You are a senior product manager. "
        "Your ONLY job is to output valid JSON. "
        "Do NOT include any explanation, markdown fences, or extra text — just raw JSON."
    ))

    def _build_synth_messages(batch_slim: list, batch_num: int, num_batches: int) -> list:
        human_text = (
            "For each requirement group below, write ONE high-quality synthesized requirement.\n\n"
            "Each item in 'synthesized' must have:\n"
            "  group_index  — integer, same as input\n"
            "  title        — 5–10 word feature-level name\n"
            '  description  — "As a [role], I want [action], so that [value]."\n'
            "  acceptance_criteria — array of 4–6 testable Given/When/Then strings\n"
            "  type         — functional | non_functional | business | constraint\n"
            "  priority     — critical | high | medium | low\n\n"
            f"Groups (batch {batch_num + 1}/{num_batches}):\n"
            + _json.dumps(batch_slim, separators=(",", ":"))
            + "\n\nOutput (raw JSON only):\n"
            '{"synthesized":[{"group_index":0,"title":"...","description":"As a ...",'
            '"acceptance_criteria":["Given ..., when ..., then ..."],'
            '"type":"functional","priority":"high"}]}'
        )
        return [_SYNTH_SYSTEM, HumanMessage(content=human_text)]

    synthesized_map: dict[int, dict] = {}
    num_batches = _math.ceil(len(groups_payload) / SYNTH_BATCH)

    for batch_num in range(num_batches):
        batch = groups_payload[batch_num * SYNTH_BATCH : (batch_num + 1) * SYNTH_BATCH]
        batch_slim = [
            {
                "group_index":  g["group_index"],
                "topic":        g["topic"],
                "requirements": g["requirements"],
                "member_count": len(g["member_ids"]),
            }
            for g in batch
        ]
        try:
            r2 = await llm_synth.ainvoke(_build_synth_messages(batch_slim, batch_num, num_batches))
            raw2 = _extract_text(r2)
            if not raw2:
                raise ValueError("LLM returned empty content for synthesis batch")
            parsed2 = _safe_json(raw2)
            for item in parsed2.get("synthesized", []):
                gi = item.get("group_index")
                if isinstance(gi, int):
                    synthesized_map[gi] = item
            logger.info(
                "Pass-2 batch %d/%d: synthesized %d groups",
                batch_num + 1, num_batches, len(parsed2.get("synthesized", [])),
            )
        except Exception as exc:
            logger.warning("Pass-2 batch %d/%d failed (%s) — will use fallback", batch_num + 1, num_batches, exc)

    # ── 8. Fallback synthesis for any group whose LLM output is missing ────────
    for g in groups_payload:
        idx = g["group_index"]
        if idx not in synthesized_map:
            titles = [r["title"] for r in g["requirements"]]
            priorities = [r["priority"] for r in g["requirements"]]
            types = [r["type"] for r in g["requirements"]]
            synthesized_map[idx] = {
                "group_index": idx,
                "title":  g["topic"],
                "description": (
                    f"As a user, I want {g['topic'].lower()}, "
                    "so that I can accomplish my goals efficiently."
                ),
                "acceptance_criteria": [f"• {t}" for t in titles],
                "type":     _most_common_type(types),
                "priority": _highest_priority(priorities),
            }

    # ── 9. Persist synthesized requirements ────────────────────────────────────
    count_row = await db.execute(
        select(func.count()).select_from(Requirement).where(
            Requirement.project_id == project_uuid
        )
    )
    next_num  = count_row.scalar_one() + 1
    now       = datetime.now(tz=timezone.utc)

    groups_created   = 0
    consolidated_ids: set[str] = set()

    for g in groups_payload:
        idx       = g["group_index"]
        synth     = synthesized_map.get(idx, {})
        member_ids  = g["member_ids"]
        member_reqs = [req_map[mid] for mid in member_ids]

        # Format acceptance_criteria array → newline-separated text
        ac_raw = synth.get("acceptance_criteria", [])
        ac_text = (
            "\n".join(ac_raw) if isinstance(ac_raw, list)
            else str(ac_raw)
        )

        # Validate & normalise type / priority
        priorities = [_req_priority(r) for r in member_reqs]
        types      = [_req_type(r) for r in member_reqs]

        req_priority = synth.get("priority", "")
        req_type     = synth.get("type", "")
        if req_priority not in VALID_PRIORITIES:
            req_priority = _highest_priority(priorities)
        if req_type not in VALID_TYPES:
            req_type = _most_common_type(types)

        title       = (synth.get("title") or g["topic"]).strip()
        description = (synth.get("description") or "").strip()
        if not description:
            description = (
                f"As a user, I want {g['topic'].lower()}, "
                "so that I can accomplish my goals efficiently."
            )

        new_req = Requirement(
            id=_uuid.uuid4(),
            organization_id=project.organization_id,
            project_id=project_uuid,
            req_number=f"REQ-{next_num:03d}",
            title=title,
            description=description,
            acceptance_criteria=ac_text,
            requirement_type=req_type,
            priority=req_priority,
            status="pending",
            is_ai_generated=True,
            confidence_score=0.93,
            tags=["consolidated", f"merged:{len(member_ids)}"],
            created_by=current_user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(new_req)
        next_num += 1
        groups_created += 1
        consolidated_ids.update(member_ids)

    # ── 10. Soft-delete originals ─────────────────────────────────────────────
    if consolidated_ids:
        member_uuids = [_uuid.UUID(rid) for rid in consolidated_ids]
        await db.execute(
            sql_update(Requirement)
            .where(Requirement.id.in_(member_uuids))
            .values(deleted_at=now, updated_at=now)
        )

    await db.commit()

    remaining = len(reqs) - len(consolidated_ids) + groups_created
    logger.info(
        "Consolidation: %d reqs → %d (%d groups created, %d merged, %d untouched)",
        len(reqs), remaining, groups_created, len(consolidated_ids),
        len(reqs) - len(consolidated_ids),
    )

    return {
        "original_count":      len(reqs),
        "consolidated_count":  remaining,
        "groups_created":      groups_created,
        "merged":              len(consolidated_ids),
        "skipped":             len(reqs) - len(consolidated_ids),
        "groups": [
            {
                "topic": g["topic"],
                "count": len(g["member_ids"]),
                "title": synthesized_map.get(g["group_index"], {}).get("title", g["topic"]),
            }
            for g in groups_payload
        ],
    }


@router.post(
    "/group-topics",
    summary="AI-group requirements by topic — adds group:<topic> tags without merging",
)
async def group_requirements_by_topic(
    project_id: str = Query(..., description="Project whose requirements to group"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Pass-1 semantic grouping only — no synthesis or deletion of originals.

    Every requirement stays individual.  Each gets a `group:<topic>` tag so the
    Requirements page can display them in collapsible sections.

    When the user generates stories afterwards, the story service reads these tags and
    produces E1-US1, E1-US2… numbering per group.
    """
    import json as _json
    import math as _math
    import re as _re
    import uuid as _uuid
    import asyncio as _asyncio
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models.requirement import Requirement
    from app.models.project import Project
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage
    from app.ai.config import AIConfig

    # ── Validate ────────────────────────────────────────────────────────────────
    try:
        project_uuid = _uuid.UUID(project_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid project_id")

    project = await db.get(Project, project_uuid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await verify_project_access(db, project_id=project_id, user_id=str(current_user.id))

    # ── Load requirements ─────────────────────────────────────────────────────
    result = await db.execute(
        select(Requirement).where(
            Requirement.project_id == project_uuid,
            Requirement.deleted_at.is_(None),
        ).order_by(Requirement.created_at.asc())
    )
    reqs = list(result.scalars().all())

    if len(reqs) < 2:
        return {
            "groups_created": 0,
            "tagged": 0,
            "groups": [],
            "message": "Need at least 2 requirements to group.",
        }

    from sqlalchemy.orm.attributes import flag_modified

    req_map = {str(r.id): r for r in reqs}
    grouping_list = [{"id": str(r.id), "title": r.title} for r in reqs]

    # Chunk size for LLM calls — large enough to see cross-cutting concerns
    GROUP_CHUNK = 50

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _extract_text(msg) -> str:
        content = msg.content if hasattr(msg, "content") else msg
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text") or block.get("content") or "")
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return ""

    def _safe_json(raw: str) -> dict:
        si, ei = raw.find("{"), raw.rfind("}")
        if si == -1 or ei <= si:
            raise ValueError(f"LLM returned no JSON: {raw[:200]!r}")
        return _json.loads(raw[si:ei + 1])

    def _normalise_topic(t: str) -> str:
        t = t.lower().strip()
        t = _re.sub(r"[^a-z0-9 ]+", " ", t)
        t = _re.sub(r"\s+", " ", t).strip()
        # Strip trailing "(1)" "(2)" suffixes so re-runs merge cleanly
        t = _re.sub(r"\s*\(\d+\)$", "", t)
        return t

    _SYSTEM = SystemMessage(content=(
        "You are a senior business analyst. "
        "Your ONLY job is to output valid JSON. "
        "Do NOT include any explanation, markdown fences, or extra text — just raw JSON."
    ))

    def _build_messages(items: list[dict]) -> list:
        n = len(items)
        compact = _json.dumps(items, separators=(",", ":"))
        human_text = (
            f"Group these {n} requirements into semantic clusters by feature domain.\n\n"
            "RULES:\n"
            f"• EVERY id must appear in exactly one group — all {n} ids must be covered.\n"
            "• Group by feature area (e.g. authentication, search, payments).\n"
            "• Put ALL requirements that belong to the same feature in the SAME group — "
            "do NOT split a feature into multiple groups just to limit group size.\n"
            "• Use a group for each distinct feature area; a group can have 1 to 30+ requirements.\n"
            "• topic: 2–6 word label — specific, no generic names like 'General'.\n\n"
            f"Requirements:\n{compact}\n\n"
            "Output format (raw JSON only):\n"
            '{"groups":[{"topic":"<label>","req_ids":["<uuid>"]}]}'
        )
        return [_SYSTEM, HumanMessage(content=human_text)]

    llm = ChatOpenAI(
        model=AIConfig._LLM_MODEL, temperature=0.1, max_tokens=4096,
        api_key=AIConfig.DEEPINFRA_API_KEY, base_url=AIConfig.DEEPINFRA_BASE_URL,
        timeout=120, max_retries=2,
    )
    llm_fallback = ChatOpenAI(
        model=AIConfig._ENTITY_MODEL, temperature=0.1, max_tokens=4096,
        api_key=AIConfig.DEEPINFRA_API_KEY, base_url=AIConfig.DEEPINFRA_BASE_URL,
        timeout=90, max_retries=1,
    )

    async def _group_chunk(chunk: list[dict], idx: int, total: int) -> list[dict]:
        msgs = _build_messages(chunk)
        for attempt, (model, label) in enumerate([(llm, "main"), (llm, "retry"), (llm_fallback, "fallback")], 1):
            if attempt == 2:
                await _asyncio.sleep(2)
            try:
                r = await model.ainvoke(msgs)
                raw = _extract_text(r)
                if not raw:
                    raise ValueError("empty response")
                parsed = _safe_json(raw)
                return [
                    {**g, "req_ids": [rid for rid in g.get("req_ids", []) if rid in req_map]}
                    for g in parsed.get("groups", [])
                    if any(rid in req_map for rid in g.get("req_ids", []))
                ]
            except Exception as exc:
                logger.warning("group-topics chunk %d/%d attempt %d (%s): %s", idx, total, attempt, label, exc)
        return []

    # ── Run Pass-1 grouping ───────────────────────────────────────────────────
    chunks = [grouping_list[i:i + GROUP_CHUNK] for i in range(0, len(grouping_list), GROUP_CHUNK)]
    chunk_results = await _asyncio.gather(*[_group_chunk(c, i + 1, len(chunks)) for i, c in enumerate(chunks)])

    # Merge same-topic groups across chunks — no artificial size cap
    topic_buckets: dict[str, dict] = {}
    for chunk_result in chunk_results:
        for g in chunk_result:
            key = _normalise_topic(g.get("topic", ""))
            if not key:
                key = "general"
            if key not in topic_buckets:
                topic_buckets[key] = {"topic": g["topic"], "req_ids": []}
            topic_buckets[key]["req_ids"].extend(g["req_ids"])

    # Keep groups intact — no splitting by size
    raw_groups: list[dict] = [
        {"topic": bucket["topic"], "req_ids": bucket["req_ids"]}
        for bucket in topic_buckets.values()
    ]

    # Pure-Python fallback if all LLM calls failed
    if not raw_groups:
        type_buckets: dict[str, list[str]] = {}
        for r in reqs:
            rtype = str(r.requirement_type.value if hasattr(r.requirement_type, "value") else r.requirement_type)
            type_buckets.setdefault(rtype, []).append(str(r.id))
        TYPE_LABELS = {"functional": "Functional", "non_functional": "Non-Functional", "business": "Business", "constraint": "Constraint"}
        for rtype, ids in type_buckets.items():
            label = TYPE_LABELS.get(rtype, rtype.replace("_", " ").title())
            ids.sort()
            raw_groups.append({"topic": label, "req_ids": ids})

    # Deduplicate IDs across groups (keep first assignment)
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for g in raw_groups:
        unique = [rid for rid in g["req_ids"] if rid not in seen_ids]
        seen_ids.update(unique)
        if unique:
            deduped.append({**g, "req_ids": unique})
    raw_groups = deduped

    # Safety net: any requirement not placed by the LLM goes to the most similar group
    # (matched by first word of title) or the largest existing group
    missed = [rid for rid in req_map if rid not in seen_ids]
    if missed:
        logger.info("group-topics: %d requirements missed by LLM — placing into best-fit groups", len(missed))
        for rid in missed:
            r_missed = req_map[rid]
            missed_title_words = set((r_missed.title or "").lower().split())
            best_group = None
            best_score = -1
            for g in raw_groups:
                # Score = number of title-word overlaps with group topic words
                topic_words = set(_normalise_topic(g["topic"]).split())
                score = len(missed_title_words & topic_words)
                if score > best_score:
                    best_score = score
                    best_group = g
            # Fall back to the largest group if no word overlap found
            if best_group is None or best_score == 0:
                best_group = max(raw_groups, key=lambda g: len(g["req_ids"]))
            best_group["req_ids"].append(rid)
            seen_ids.add(rid)

    if not raw_groups:
        raw_groups.append({"topic": "General Requirements", "req_ids": list(req_map.keys())})

    # ── Tag requirements with their group ─────────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    tagged_count = 0
    for g in raw_groups:
        topic = g["topic"]
        for rid in g["req_ids"]:
            r = req_map.get(rid)
            if r:
                existing_tags = list(r.tags or [])
                existing_tags = [t for t in existing_tags if not t.startswith("group:")]
                existing_tags.append(f"group:{topic}")
                r.tags = existing_tags
                flag_modified(r, "tags")   # force SQLAlchemy to detect JSONB change
                r.updated_at = now
                tagged_count += 1

    await db.commit()

    logger.info(
        "group-topics: %d groups, %d requirements tagged for project %s",
        len(raw_groups), tagged_count, project_uuid,
    )

    return {
        "groups_created": len(raw_groups),
        "tagged": tagged_count,
        "groups": [
            {"topic": g["topic"], "count": len(g["req_ids"]), "epic_id": f"E{i + 1}"}
            for i, g in enumerate(raw_groups)
        ],
    }


@router.get(
    "/{req_id}",
    summary="Get requirement details",
)
async def get_requirement(
    req_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = RequirementService(db)
    req = await svc.get_by_id(req_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found.")
    await verify_project_access(db, project_id=str(req.project_id), user_id=str(current_user.id))
    return _serialize_requirement(req)


@router.patch(
    "/{req_id}",
    summary="Update requirement",
)
async def update_requirement(
    req_id: str,
    payload: RequirementUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = RequirementService(db)
    req = await svc.get_by_id(req_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found.")

    await verify_project_access(db, project_id=str(req.project_id), user_id=str(current_user.id))

    # ── Map frontend field names / values → DB column names / values ──
    #
    # Frontend status  │  DB status (ApprovalStatus enum)
    # ─────────────────┼─────────────────────────────────
    # "draft"          │  "pending"
    # "in_progress"    │  "in_review"
    # "approved"       │  "approved"
    # "rejected"       │  "rejected"
    FRONTEND_TO_DB_STATUS = {
        "draft":       "pending",
        "in_progress": "in_review",
        "approved":    "approved",
        "rejected":    "rejected",
    }

    raw = payload.model_dump(exclude_none=True)

    # "type" → "requirement_type"
    if "type" in raw:
        raw["requirement_type"] = raw.pop("type")

    # frontend status → DB status
    if "status" in raw:
        raw["status"] = FRONTEND_TO_DB_STATUS.get(raw["status"], raw["status"])

    # "acceptance_criteria" arrives as list[str] from Pydantic; DB column is text
    if "acceptance_criteria" in raw:
        ac = raw["acceptance_criteria"]
        raw["acceptance_criteria"] = "\n".join(ac) if isinstance(ac, list) else str(ac)

    updated = await svc.update_requirement(
        req_id=req_id,
        data=raw,
        updated_by=str(current_user.id),
    )
    return _serialize_requirement(updated)


@router.delete(
    "/{req_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete requirement",
)
async def delete_requirement(
    req_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = RequirementService(db)
    req = await svc.get_by_id(req_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found.")
    await verify_project_access(db, project_id=str(req.project_id), user_id=str(current_user.id))
    await svc.delete_requirement(req_id=req_id)


@router.post(
    "/bulk",
    summary="Bulk create requirements",
)
async def bulk_create_requirements(
    items: list[RequirementCreateRequest],
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple requirements at once (max 100)."""
    if len(items) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create more than 100 requirements at once.",
        )
    # Verify access for all unique project IDs in the batch
    seen_project_ids: set[str] = set()
    for item in items:
        if item.project_id not in seen_project_ids:
            await verify_project_access(db, project_id=item.project_id, user_id=str(current_user.id))
            seen_project_ids.add(item.project_id)
    svc = RequirementService(db)
    return await svc.bulk_create(
        items=[{**item.model_dump(), "created_by": str(current_user.id)} for item in items]
    )
