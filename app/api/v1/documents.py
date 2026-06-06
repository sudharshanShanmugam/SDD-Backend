"""
Document management API routes.
Upload, process, list documents with AI extraction support.
"""
import logging
import mimetypes
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.services.document_service import DocumentService
from app.workers.tasks.document_tasks import generate_embeddings, process_document

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/msword",
    "text/plain",
    "text/markdown",
    "application/json",
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class DocumentResponse(BaseModel):
    id: str
    original_filename: str
    content_type: str
    file_size_bytes: int
    status: str
    project_id: str | None = None
    page_count: int | None = None
    processing_error: str | None = None
    uploaded_by: str | None = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_safe(cls, doc) -> "DocumentResponse":
        return cls(
            id=str(doc.id),
            original_filename=doc.original_filename,
            content_type=doc.content_type,
            file_size_bytes=doc.file_size_bytes,
            status=str(doc.status.value) if hasattr(doc.status, "value") else str(doc.status),
            project_id=str(doc.project_id) if doc.project_id else None,
            page_count=doc.page_count,
            processing_error=doc.processing_error,
            uploaded_by=str(doc.uploaded_by) if doc.uploaded_by else None,
            created_at=doc.created_at.isoformat() if doc.created_at else "",
            updated_at=doc.updated_at.isoformat() if doc.updated_at else "",
        )


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int


class ChunkResponse(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    content: str
    metadata: dict
    token_count: int | None

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for processing",
)
async def upload_document(
    file: Annotated[UploadFile, File(description="Document file (PDF, DOCX, PPTX, XLSX)")],
    project_id: str | None = Form(default=None),
    tags: str | None = Form(default=None, description="Comma-separated tags"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document file for AI-powered extraction.

    Supported formats: PDF, DOCX, PPTX, XLSX, TXT, MD.
    Max file size: 50 MB.

    Returns immediately with status=pending; processing happens async.
    """
    # Validate MIME type
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {content_type}. Allowed: PDF, DOCX, PPTX, XLSX, TXT, MD.",
        )

    # Read file and check size
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {MAX_FILE_SIZE_BYTES // (1024*1024)} MB.",
        )

    svc = DocumentService(db)
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    document = await svc.create_document(
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        content_type=content_type,
        project_id=project_id,
        tags=tag_list,
        uploaded_by=str(current_user.id),
    )

    # Queue async processing (best-effort — Celery may not be running in dev)
    try:
        process_document.delay(str(document.id))
    except Exception as exc:
        logger.warning("Could not queue processing task for document %s: %s", document.id, exc)

    logger.info("Document uploaded: %s (id=%s)", document.original_filename, document.id)
    return DocumentResponse.from_orm_safe(document)


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
)
async def list_documents(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents with pagination and filters."""
    svc = DocumentService(db)
    result = await svc.list_documents(
        user_id=str(current_user.id),
        project_id=project_id,
        status=status,
        file_type=file_type,
        search=search,
        page=page,
        page_size=page_size,
    )
    return DocumentListResponse(
        items=[DocumentResponse.from_orm_safe(d) for d in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document details",
)
async def get_document(
    document_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get document metadata and processing status."""
    svc = DocumentService(db)
    doc = await svc.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return DocumentResponse.from_orm_safe(doc)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete document",
)
async def delete_document(
    document_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and all its chunks."""
    svc = DocumentService(db)
    doc = await svc.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    uploader = str(doc.uploaded_by) if doc.uploaded_by else None
    user_role = getattr(current_user, "role", None)
    if uploader != str(current_user.id) and user_role not in ("admin", "super_admin", "org_admin", "owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    await svc.delete_document(document_id=document_id)


@router.post(
    "/{document_id}/reprocess",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger AI reprocessing of document",
)
async def reprocess_document(
    document_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-trigger document parsing and embedding generation."""
    svc = DocumentService(db)
    doc = await svc.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    await svc.update_status(document_id=document_id, status="pending")
    process_document.delay(document_id)

    return {"message": "Reprocessing triggered.", "document_id": document_id}


@router.post(
    "/{document_id}/process",
    summary="Synchronously parse and chunk a document (no Celery required)",
)
async def process_document_sync(
    document_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Parse the document, split into chunks, and store them in the DB.
    Runs synchronously in the request — no Celery worker needed.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    # Read file bytes from local storage
    import os
    file_path = doc.file_path
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File not found on disk: {file_path}. Re-upload the document.",
        )

    file_bytes = open(file_path, "rb").read()

    # Parse text
    try:
        full_text, meta = await svc.parse_document(file_bytes, doc.original_filename, doc.content_type)
    except Exception as exc:
        await svc.update_status(document_id=document_id, status="failed", error_message=str(exc))
        raise HTTPException(status_code=422, detail=f"Parse failed: {exc}")

    # Chunk
    chunks = svc.chunk_document(full_text, {"document_id": document_id, **meta})

    # Persist chunks (best-effort — table may not exist yet)
    chunk_count = 0
    try:
        await svc.store_chunks(chunks, document_id)
        chunk_count = len(chunks)
    except Exception as exc:
        logger.warning("Could not store chunks for %s: %s", document_id, exc)

    # Update document record
    await svc.update_status(
        document_id=document_id,
        status="processed",
        page_count=meta.get("page_count"),
        chunk_count=chunk_count,
    )

    logger.info("Processed document %s: %d chunks", document_id, chunk_count)
    return {
        "document_id": document_id,
        "status": "processed",
        "page_count": meta.get("page_count"),
        "chunk_count": chunk_count,
        "word_count": len(full_text.split()) if full_text else 0,
    }


@router.post(
    "/{document_id}/extract-requirements",
    summary="Synchronously extract requirements from a processed document using AI",
)
async def extract_requirements_sync(
    document_id: str,
    project_id: str | None = Query(default=None),
    max_requirements: int = Query(
        default=0,
        ge=0,
        description="Max requirements to store. 0 = no limit (store everything the LLM finds).",
    ),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Use an LLM to extract structured software requirements from the document text.

    Reads file from disk → parses text → calls DeepInfra LLM → stores Requirement rows.
    Falls back to rule-based extraction when LLM is unavailable.
    No Celery required.
    """
    import json
    import os
    import re
    import uuid as _uuid
    from datetime import datetime, timezone
    from sqlalchemy import func as sqlfunc
    from sqlalchemy import select as sql_select
    from app.models.requirement import Requirement
    from app.core.constants import ApprovalStatus, RequirementPriority, RequirementType
    from app.core.config import settings

    svc = DocumentService(db)
    doc = await svc.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    # ── Build full text ────────────────────────────────────────────────────
    full_text = ""

    # Best: re-parse from file on disk (full fidelity)
    if doc.file_path and os.path.exists(doc.file_path):
        try:
            file_bytes = open(doc.file_path, "rb").read()
            full_text, _ = await svc.parse_document(file_bytes, doc.original_filename, doc.content_type)
        except Exception as exc:
            logger.warning("Could not re-parse file for extraction: %s", exc)

    # Fallback: stored chunk summaries
    if not full_text and doc.parsed_content and "chunks" in doc.parsed_content:
        full_text = "\n\n".join(c.get("content", "") for c in doc.parsed_content["chunks"][:40])

    # Last resort: raw_text column
    if not full_text and doc.raw_text:
        full_text = doc.raw_text

    if not full_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No text to extract from. Process the document first via POST /{id}/process",
        )

    # ── Resolve project_id ─────────────────────────────────────────────────
    actual_project_id = project_id or (str(doc.project_id) if doc.project_id else None)
    if not actual_project_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No project_id. Pass ?project_id=<id> or re-upload with a project.",
        )

    # ── LLM extraction — chunked multi-pass ──────────────────────────────
    #
    # Strategy: smaller chunks (12 000 chars ≈ 3 000 tokens of document text)
    # so each LLM call sees a focused section with fewer requirements, and a
    # generous max_tokens budget (8 000) so the response is never truncated.
    #
    # 12 000 chars at ~4 chars/token ≈ 3 000 input tokens.
    # With system prompt (~500 tokens) + instructions (~600 tokens) the total
    # input is ~4 100 tokens.  With max_tokens=8 000 for the response the
    # model can return ~60-80 fully detailed requirements per chunk.
    # At MAX_CHUNKS=40 we cover documents up to ~480 000 chars (≈ 240 pages).
    # ──────────────────────────────────────────────────────────────────────
    CHUNK_SIZE    = 12_000   # chars per LLM call — smaller = fewer reqs per pass = less truncation
    CHUNK_OVERLAP =  1_000   # generous overlap keeps requirements that straddle section boundaries
    MAX_CHUNKS    =     40   # cover up to ~480 000 chars (≈ 240-page document)

    extracted_raw: list[dict] = []
    method_used = "llm"
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.DEEPINFRA_API_KEY,
            base_url=settings.DEEPINFRA_BASE_URL,
        )

        # ── Build chunk list ────────────────────────────────────────────
        chunks: list[str] = []
        start = 0
        while start < len(full_text):
            end = start + CHUNK_SIZE
            chunks.append(full_text[start:end])
            if end >= len(full_text):
                break
            start = end - CHUNK_OVERLAP   # overlap keeps boundary requirements intact
        chunks = chunks[:MAX_CHUNKS]

        total_chars = len(full_text)
        logger.info(
            "Extracting requirements from document %s: %d chars → %d chunk(s)",
            document_id, total_chars, len(chunks),
        )

        # ── Shared prompt sections ──────────────────────────────────────
        system_message = (
            "You are an expert business analyst and requirements engineer with 15+ years of "
            "experience writing ISO-29148-compliant Software Requirements Specifications. "
            "You extract precise, atomic, testable requirements from technical documents. "
            "You never invent requirements that are not present in the source text."
        )

        def build_user_message(chunk_text: str, chunk_idx: int, total_chunks: int) -> str:
            chunk_note = (
                f"[Document section {chunk_idx + 1} of {total_chunks} — extract ALL requirements from THIS section only]\n\n"
                if total_chunks > 1 else ""
            )
            return (
                f"{chunk_note}"
                "Your task: extract EVERY SINGLE software requirement present in this section.\n"
                "This is exhaustive extraction — do NOT stop early, do NOT summarise, do NOT sample.\n"
                "A thorough analyst would typically find 15–60 requirements in a section this size. Find them all.\n\n"

                "━━━ WHAT TO EXTRACT ━━━\n"
                "✓ Explicit: shall, must, will, is required to, needs to, has to.\n"
                "✓ Implicit: requirements described through user flows, screen descriptions, data rules.\n"
                "✓ Non-functional: response time, uptime, concurrency, security, accessibility, data retention.\n"
                "✓ Business rules: validation rules, approval workflows, pricing logic, role permissions.\n"
                "✓ Constraints: browser support, OS compatibility, API version requirements.\n"
                "✓ Every form field validation, every error state, every edge case described.\n\n"

                "━━━ WHAT TO SKIP ━━━\n"
                "✗ Table-of-contents entries and section headings that state no requirement.\n"
                "✗ Pure narrative with no actionable constraint or capability.\n"
                "✗ Exact duplicate of a requirement you already output in this response.\n\n"

                "━━━ OUTPUT FORMAT ━━━\n"
                "Return a JSON array (opening [ on line 1, closing ] on the last line).\n"
                "Every element must have EXACTLY these keys — no extras, no omissions:\n"
                '{"title":"<5-12 word imperative, e.g. User Must Reset Password via Email>",'
                '"description":"<The system shall … 1-3 sentences, max 300 chars>",'
                '"type":"<functional|non_functional|business|constraint>",'
                '"priority":"<critical|high|medium|low>",'
                '"acceptance_criteria":"<2-3 Given/When/Then lines>",'
                '"tags":["<tag1>","<tag2>"],'
                '"confidence":<0.50-1.00>}\n\n'

                "━━━ COMPLETENESS CHECK ━━━\n"
                "Before closing the array, re-read the document section and ask yourself:\n"
                "  'Is there ANY requirement I have not yet included?'\n"
                "If yes, add it. Only close ] when you are certain you have captured everything.\n\n"

                "Return ONLY the JSON array — no markdown fences, no commentary before or after.\n\n"
                f"━━━ DOCUMENT SECTION ━━━\n{chunk_text}"
            )

        # ── Helper: parse one LLM response ──────────────────────────────
        def parse_llm_response(raw: str) -> list[dict]:
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE).strip()
            raw = re.sub(r"\s*```$",          "", raw, flags=re.MULTILINE).strip()
            try:
                result = json.loads(raw)
                return result if isinstance(result, list) else []
            except json.JSONDecodeError:
                # Partial / truncated response — recover complete objects
                recovered = []
                for obj_str in re.findall(r'\{(?:[^{}]|\{[^{}]*\})*\}', raw, re.DOTALL):
                    try:
                        recovered.append(json.loads(obj_str))
                    except json.JSONDecodeError:
                        fixed = re.sub(r',\s*([}\]])', r'\1', obj_str).replace("'", '"')
                        try:
                            recovered.append(json.loads(fixed))
                        except json.JSONDecodeError:
                            pass
                return recovered

        # ── Run extraction on each chunk ────────────────────────────────
        all_raw: list[dict] = []
        for chunk_idx, chunk_text in enumerate(chunks):
            logger.info(
                "  chunk %d/%d — %d chars",
                chunk_idx + 1, len(chunks), len(chunk_text),
            )
            user_msg = build_user_message(chunk_text, chunk_idx, len(chunks))
            resp = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user",   "content": user_msg},
                ],
                max_tokens=8_000,   # 8 000 tokens ≈ 60-80 full requirements per chunk
                temperature=0.1,
            )
            raw_content = resp.choices[0].message.content.strip()
            finish_reason = resp.choices[0].finish_reason

            # ── Truncation recovery: if the model hit the token limit mid-JSON,
            #    do one continuation pass to complete the array.
            if finish_reason == "length" and not raw_content.rstrip().endswith("]"):
                logger.warning(
                    "  chunk %d hit token limit (finish_reason=length) — attempting continuation",
                    chunk_idx + 1,
                )
                try:
                    cont_resp = await client.chat.completions.create(
                        model=settings.LLM_MODEL,
                        messages=[
                            {"role": "system",    "content": system_message},
                            {"role": "user",      "content": user_msg},
                            {"role": "assistant", "content": raw_content},
                            {"role": "user",      "content":
                                "Continue the JSON array from exactly where you left off. "
                                "Do not repeat already-output requirements. "
                                "Close the array with ] when done."},
                        ],
                        max_tokens=8_000,
                        temperature=0.1,
                    )
                    continuation = cont_resp.choices[0].message.content.strip()
                    # Stitch: find the last complete object in raw_content, then append continuation
                    last_brace = raw_content.rfind("}")
                    if last_brace != -1:
                        raw_content = raw_content[: last_brace + 1] + "," + continuation
                    else:
                        raw_content = raw_content + continuation
                except Exception as cont_exc:
                    logger.warning("  continuation pass failed: %s", cont_exc)

            chunk_raw = parse_llm_response(raw_content)
            logger.info("    → %d requirements from chunk %d (finish=%s)", len(chunk_raw), chunk_idx + 1, finish_reason)
            all_raw.extend(chunk_raw)

        # ── Quality filter ──────────────────────────────────────────────
        required_keys = {"title", "description"}
        all_raw = [
            r for r in all_raw
            if isinstance(r, dict)
            and required_keys.issubset(r.keys())
            and str(r.get("title", "")).strip()
            and str(r.get("description", "")).strip()
        ]

        # ── Cross-chunk deduplication ───────────────────────────────────
        # Two requirements are considered duplicates if their normalised titles
        # share more than 80 % of words (simple token-overlap check — no deps).
        def _token_overlap(a: str, b: str) -> float:
            ta = set(re.sub(r"[^a-z0-9 ]", "", a.lower()).split())
            tb = set(re.sub(r"[^a-z0-9 ]", "", b.lower()).split())
            if not ta or not tb:
                return 0.0
            return len(ta & tb) / max(len(ta), len(tb))

        seen_titles: list[str] = []
        deduped: list[dict] = []
        for r in all_raw:
            title = str(r.get("title", "")).strip()
            # Use 0.85 threshold: merges true duplicates from chunk overlap,
            # but keeps requirements that share a few words but are distinct.
            is_dup = any(_token_overlap(title, t) > 0.85 for t in seen_titles)
            if not is_dup:
                seen_titles.append(title)
                deduped.append(r)

        extracted_raw = deduped
        logger.info(
            "LLM extracted %d requirements total (%d after dedup) from %d chunk(s) of document %s",
            len(all_raw), len(extracted_raw), len(chunks), document_id,
        )

    except Exception as exc:
        logger.warning("LLM extraction failed (%s); using heuristic fallback", exc)
        method_used = "heuristic"
        extracted_raw = _heuristic_extract_requirements(full_text)

    # ── Persist requirements ───────────────────────────────────────────────
    count_row = await db.execute(
        sql_select(sqlfunc.count()).select_from(Requirement).where(
            Requirement.project_id == _uuid.UUID(actual_project_id)
        )
    )
    existing_count = count_row.scalar_one()

    valid_types = {t.value for t in RequirementType}
    valid_priorities = {p.value for p in RequirementPriority}
    now = datetime.now(tz=timezone.utc)

    req_objects: list[Requirement] = []
    # Apply caller's limit (0 = unlimited — store everything the LLM found)
    batch = extracted_raw if max_requirements == 0 else extracted_raw[:max_requirements]

    for i, r in enumerate(batch):
        # ── Type ────────────────────────────────────────────────────────
        req_type = str(r.get("type", "functional")).strip().lower()
        if req_type not in valid_types:
            req_type = "functional"

        # ── Priority ─────────────────────────────────────────────────────
        req_priority = str(r.get("priority", "medium")).strip().lower()
        if req_priority not in valid_priorities:
            req_priority = "medium"

        # ── Acceptance criteria ───────────────────────────────────────────
        ac_raw = r.get("acceptance_criteria") or ""
        if isinstance(ac_raw, list):
            ac_raw = "\n".join(str(x) for x in ac_raw)
        acceptance_criteria = str(ac_raw).strip()

        # ── Tags ──────────────────────────────────────────────────────────
        tags_raw = r.get("tags") or []
        if isinstance(tags_raw, str):
            tags_raw = [t.strip() for t in tags_raw.split(",") if t.strip()]
        tags = [str(t)[:50] for t in tags_raw if t][:10]   # max 10 tags, 50 chars each

        # ── Confidence ────────────────────────────────────────────────────
        try:
            confidence = float(r.get("confidence", 0.80))
            confidence = max(0.0, min(1.0, confidence))     # clamp to [0, 1]
        except (TypeError, ValueError):
            confidence = 0.80

        req = Requirement(
            id=_uuid.uuid4(),
            organization_id=doc.organization_id,
            project_id=_uuid.UUID(actual_project_id),
            source_document_id=doc.id,
            req_number=f"REQ-{existing_count + i + 1:03d}",
            title=(r.get("title") or "Untitled Requirement")[:500],
            description=(r.get("description") or r.get("title") or "")[:2000],
            acceptance_criteria=acceptance_criteria,
            requirement_type=req_type,
            priority=req_priority,
            status=ApprovalStatus.PENDING.value,
            confidence_score=confidence,
            is_ai_generated=True,
            created_by=_uuid.UUID(str(current_user.id)) if current_user else None,
            tags=tags,
            created_at=now,
            updated_at=now,
        )
        req_objects.append(req)

    db.add_all(req_objects)
    await db.commit()

    logger.info(
        "Stored %d requirements (method=%s) for document %s",
        len(req_objects), method_used, document_id
    )
    return {
        "document_id": document_id,
        "requirements_extracted": len(req_objects),
        "project_id": actual_project_id,
        "method": method_used,
        "requirements": [
            {
                "id": str(r.id),
                "req_number": r.req_number,
                "title": r.title,
                "type": str(r.requirement_type),
                "priority": str(r.priority),
            }
            for r in req_objects
        ],
    }


def _heuristic_extract_requirements(text: str) -> list[dict]:
    """
    Rule-based fallback used when the LLM is unavailable.
    Produces structured requirements with basic acceptance criteria and
    confidence scores calibrated by how explicit the requirement language is.
    """
    import re

    # Requirement signal patterns — ordered by confidence
    EXPLICIT   = re.compile(r"\b(shall|must|is required to|are required to)\b", re.IGNORECASE)
    STRONG     = re.compile(r"\b(will|needs to|has to|need to)\b", re.IGNORECASE)
    IMPLICIT   = re.compile(r"\b(should|ought to|expected to|is expected)\b", re.IGNORECASE)
    NUMBERED   = re.compile(r"^\s*(?:\d+[\.\)])+\s+.{20,}")

    NFR_TERMS  = re.compile(
        r"\b(performance|security|availab|scalab|reliab|latency|throughput|"
        r"usability|accessibility|response.?time|uptime|sla|tls|encrypt|audit)\b",
        re.IGNORECASE,
    )
    BIZ_TERMS  = re.compile(
        r"\b(compliance|regulatory|gdpr|hipaa|policy|business rule|sla|contract)\b",
        re.IGNORECASE,
    )
    CONSTRAINT = re.compile(
        r"\b(must.{0,20}(run|support|use|built|deploy)|only.{0,15}(browser|platform|os)|"
        r"compatible.{0,15}(with|to)|limited.{0,15}to)\b",
        re.IGNORECASE,
    )
    CRITICAL_KW = re.compile(r"\b(critical|mandatory|essential|must not|shall not|security|safety)\b", re.IGNORECASE)
    HIGH_KW     = re.compile(r"\b(must|required|primary|core|fundamental)\b", re.IGNORECASE)
    LOW_KW      = re.compile(r"\b(should|optionally|nice.to.have|may|consider)\b", re.IGNORECASE)

    def _classify_type(line: str) -> str:
        if CONSTRAINT.search(line): return "constraint"
        if NFR_TERMS.search(line):  return "non_functional"
        if BIZ_TERMS.search(line):  return "business"
        return "functional"

    def _classify_priority(line: str) -> str:
        if CRITICAL_KW.search(line): return "critical"
        if HIGH_KW.search(line):     return "high"
        if LOW_KW.search(line):      return "low"
        return "medium"

    def _score_confidence(line: str) -> float:
        if EXPLICIT.search(line):  return 0.82
        if STRONG.search(line):    return 0.70
        if NUMBERED.match(line):   return 0.65
        if IMPLICIT.search(line):  return 0.58
        return 0.52

    def _make_title(line: str) -> str:
        """Trim verbs and articles to form a concise title."""
        # Remove leading numbers/bullets
        clean = re.sub(r"^\s*[\d\.\)\-\*•]+\s*", "", line).strip()
        # Capitalize first word
        if clean:
            clean = clean[0].upper() + clean[1:]
        # Truncate at 100 chars, cut at last word boundary
        if len(clean) > 100:
            clean = clean[:97].rsplit(" ", 1)[0] + "…"
        return clean

    def _make_acceptance_criteria(line: str, req_type: str) -> str:
        """Generate a minimal Given/When/Then criterion from the requirement line."""
        # Extract the verb+object portion for the "Then" clause
        subj = "the user" if re.search(r"\b(user|users|operator|admin)\b", line, re.IGNORECASE) else "the system"
        verb_match = re.search(
            r"\b(?:shall|must|will|can|needs to|is required to)\s+(.{10,80}?)(?:\.|,|;|$)",
            line, re.IGNORECASE
        )
        then_clause = verb_match.group(1).strip() if verb_match else "the expected behaviour is achieved"

        if req_type == "non_functional":
            return (
                f"Given the system is operating under normal load\n"
                f"When the relevant operation is performed\n"
                f"Then {then_clause}"
            )
        elif req_type == "business":
            return (
                f"Given the applicable business rule is in effect\n"
                f"When {subj} attempts the described action\n"
                f"Then {then_clause}"
            )
        else:
            return (
                f"Given {subj} is authenticated and has appropriate permissions\n"
                f"When the relevant action is triggered\n"
                f"Then {then_clause}"
            )

    results: list[dict] = []
    seen: set[str] = set()

    for line in text.split("\n"):
        line = line.strip()
        if not (30 <= len(line) <= 700):
            continue

        is_req = (
            EXPLICIT.search(line)
            or STRONG.search(line)
            or IMPLICIT.search(line)
            or NUMBERED.match(line)
        )
        if not is_req:
            continue

        key = line[:80].lower()
        if key in seen:
            continue
        seen.add(key)

        req_type  = _classify_type(line)
        priority  = _classify_priority(line)
        confidence = _score_confidence(line)
        title     = _make_title(line)
        ac        = _make_acceptance_criteria(line, req_type)

        # Extract simple domain tags from the line
        tag_patterns = {
            "authentication": r"\b(login|auth|password|credential|sso|oauth|jwt)\b",
            "security":       r"\b(encrypt|tls|ssl|secure|xss|csrf|injection)\b",
            "performance":    r"\b(latency|throughput|response.?time|sla|uptime)\b",
            "data":           r"\b(data|database|storage|persist|record|field)\b",
            "ui":             r"\b(interface|ui|screen|page|display|render|button|form)\b",
            "api":            r"\b(api|endpoint|rest|graphql|webhook|integration)\b",
            "notification":   r"\b(email|notify|alert|push|sms|message)\b",
            "reporting":      r"\b(report|export|csv|pdf|analytics|dashboard)\b",
        }
        tags = [tag for tag, pattern in tag_patterns.items() if re.search(pattern, line, re.IGNORECASE)]

        results.append({
            "title":               title,
            "description":         line[:350],
            "type":                req_type,
            "priority":            priority,
            "acceptance_criteria": ac,
            "tags":                tags,
            "confidence":          confidence,
        })

    return results[:50]


@router.get(
    "/{document_id}/chunks",
    response_model=list[ChunkResponse],
    summary="Get document chunks for RAG",
)
async def get_document_chunks(
    document_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the text chunks extracted from a document, used for RAG retrieval."""
    svc = DocumentService(db)
    doc = await svc.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return await svc.get_chunks(
        document_id=document_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{document_id}/download",
    summary="Get presigned download URL",
)
async def get_download_url(
    document_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a presigned URL to download the original document from object storage."""
    svc = DocumentService(db)
    doc = await svc.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    url = await svc.get_download_url(document_id=document_id)
    return {"url": url, "expires_in": 3600}
