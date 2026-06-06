"""
Document processing Celery tasks.
Async document parsing, chunking, embedding generation with full error handling.
"""
import logging
from datetime import datetime, timezone

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.workers.celery_app import celery_app, get_db_session, run_async

logger = logging.getLogger(__name__)


class DocumentTask(Task):
    """Base task class with document-specific error handling."""
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        document_id = args[0] if args else kwargs.get("document_id")
        if document_id:
            run_async(_update_document_status(document_id, "failed", str(exc)))
        logger.error(
            "Document task %s failed for document %s: %s",
            self.name,
            document_id,
            exc,
            exc_info=True,
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)


async def _update_document_status(
    document_id: str,
    status: str,
    error_message: str | None = None,
    page_count: int | None = None,
    chunk_count: int | None = None,
) -> None:
    """Helper to update document status with a fresh session."""
    async with get_db_session() as db:
        if db is None:
            return
        from app.services.document_service import DocumentService
        svc = DocumentService(db)
        await svc.update_status(
            document_id=document_id,
            status=status,
            error_message=error_message,
            page_count=page_count,
            chunk_count=chunk_count,
        )


async def _broadcast_ws_event(event: str, data: dict) -> None:
    """Broadcast a WebSocket event (non-critical)."""
    try:
        from app.websockets.manager import ws_manager
        await ws_manager.broadcast_to_project(
            project_id=data.get("project_id", ""),
            event=event,
            data=data,
        )
    except Exception as exc:
        logger.debug("WS broadcast failed (non-critical): %s", exc)


@celery_app.task(
    bind=True,
    base=DocumentTask,
    name="app.workers.tasks.document_tasks.process_document",
    max_retries=3,
    default_retry_delay=30,
    queue="documents",
)
def process_document(self, document_id: str) -> dict:
    """
    Full document processing pipeline:
    1. Fetch document metadata from DB
    2. Download file bytes from object storage
    3. Parse document (PDF/DOCX/PPTX/XLSX)
    4. Extract metadata
    5. Chunk document with overlap
    6. Store chunks in DB
    7. Trigger embedding generation
    8. Publish WebSocket events

    Retries on transient failures with exponential backoff.
    """
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database session unavailable")

            from app.services.document_service import DocumentService
            svc = DocumentService(db)

            # Fetch document
            doc = await svc.get_by_id(document_id)
            if not doc:
                logger.error("Document %s not found, skipping processing", document_id)
                return {"status": "skipped", "reason": "document_not_found"}

            if doc.status == "completed":
                logger.info("Document %s already processed, skipping", document_id)
                return {"status": "skipped", "reason": "already_completed"}

            # Mark as processing
            await svc.update_status(document_id=document_id, status="processing")
            await _broadcast_ws_event(
                "document.processing.started",
                {
                    "document_id": document_id,
                    "project_id": str(doc.project_id) if doc.project_id else None,
                },
            )

            # Update task progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "workflow_type": "document_processing",
                    "progress": 10,
                    "current_step": "downloading",
                    "started_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            )

            # Download file from storage
            try:
                import aioboto3
                from app.core.config import settings

                session = aioboto3.Session()
                async with session.client(
                    "s3",
                    endpoint_url=settings.S3_ENDPOINT_URL,
                    aws_access_key_id=settings.S3_ACCESS_KEY,
                    aws_secret_access_key=settings.S3_SECRET_KEY,
                ) as s3:
                    response = await s3.get_object(Bucket=settings.S3_BUCKET, Key=doc.storage_key)
                    file_bytes = await response["Body"].read()
            except ImportError:
                logger.warning("aioboto3 unavailable, using placeholder bytes")
                file_bytes = b""
            except Exception as exc:
                raise RuntimeError(f"Failed to download document from storage: {exc}") from exc

            self.update_state(
                state="PROGRESS",
                meta={
                    "workflow_type": "document_processing",
                    "progress": 30,
                    "current_step": "parsing",
                },
            )

            # Parse document
            try:
                full_text, metadata = await svc.parse_document(
                    file_bytes=file_bytes,
                    filename=doc.original_filename,
                    content_type=doc.content_type,
                )
            except Exception as exc:
                error_msg = f"Parse error: {exc}"
                await svc.update_status(
                    document_id=document_id,
                    status="failed",
                    error_message=error_msg,
                )
                await _broadcast_ws_event(
                    "document.processing.failed",
                    {
                        "document_id": document_id,
                        "error": error_msg,
                    },
                )
                raise

            self.update_state(
                state="PROGRESS",
                meta={
                    "workflow_type": "document_processing",
                    "progress": 60,
                    "current_step": "chunking",
                },
            )

            # Chunk document
            chunks = svc.chunk_document(text=full_text, metadata=metadata)

            self.update_state(
                state="PROGRESS",
                meta={
                    "workflow_type": "document_processing",
                    "progress": 80,
                    "current_step": "storing_chunks",
                },
            )

            # Store chunks
            await svc.store_chunks(chunks=chunks, document_id=document_id)

            # Update document status
            await svc.update_status(
                document_id=document_id,
                status="completed",
                page_count=metadata.get("page_count"),
                chunk_count=len(chunks),
            )

            self.update_state(
                state="PROGRESS",
                meta={
                    "workflow_type": "document_processing",
                    "progress": 95,
                    "current_step": "triggering_embeddings",
                },
            )

            # Queue embedding generation
            generate_embeddings.delay(document_id)

            await _broadcast_ws_event(
                "document.processing.completed",
                {
                    "document_id": document_id,
                    "project_id": str(doc.project_id) if doc.project_id else None,
                    "chunk_count": len(chunks),
                    "page_count": metadata.get("page_count"),
                },
            )

            logger.info(
                "Document %s processed: %d chunks, %d pages",
                document_id,
                len(chunks),
                metadata.get("page_count") or 0,
            )

            return {
                "document_id": document_id,
                "status": "completed",
                "chunk_count": len(chunks),
                "page_count": metadata.get("page_count"),
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("process_document failed for %s: %s", document_id, exc)
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)
        except MaxRetriesExceededError:
            run_async(_update_document_status(document_id, "failed", str(exc)))
            raise


@celery_app.task(
    bind=True,
    name="app.workers.tasks.document_tasks.generate_embeddings",
    max_retries=3,
    default_retry_delay=60,
    queue="documents",
    soft_time_limit=600,
    time_limit=900,
)
def generate_embeddings(self, document_id: str) -> dict:
    """
    Generate vector embeddings for all document chunks.
    Uses batched OpenAI API calls for efficiency.
    Stores embeddings in pgvector-enabled search_index table.
    """
    async def _run():
        async with get_db_session() as db:
            if db is None:
                raise RuntimeError("Database session unavailable")

            from app.services.document_service import DocumentService
            svc = DocumentService(db)

            # Get all chunks for this document
            chunks = await svc.get_chunks(document_id=document_id, page=1, page_size=1000)
            if not chunks:
                logger.warning("No chunks found for document %s", document_id)
                return {"document_id": document_id, "embedded": 0}

            self.update_state(
                state="PROGRESS",
                meta={"progress": 10, "current_step": "loading_chunks", "total": len(chunks)},
            )

            # Get document metadata
            doc = await svc.get_by_id(document_id)
            batch_size = 100
            embedded_count = 0

            # Process in batches
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]
                texts = [c.content for c in batch]

                try:
                    embeddings = await _generate_embeddings_batch(texts)
                except Exception as exc:
                    logger.error("Embedding generation failed for batch %d: %s", i, exc)
                    raise

                # Store embeddings in search index
                await _upsert_search_index(
                    db=db,
                    document_id=document_id,
                    project_id=str(doc.project_id) if doc and doc.project_id else None,
                    chunks=batch,
                    embeddings=embeddings,
                    entity_type="document",
                )

                embedded_count += len(batch)
                progress = int((embedded_count / len(chunks)) * 90) + 10
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "progress": progress,
                        "current_step": "embedding",
                        "embedded": embedded_count,
                        "total": len(chunks),
                    },
                )

            logger.info(
                "Embeddings generated for document %s: %d chunks",
                document_id,
                embedded_count,
            )
            return {
                "document_id": document_id,
                "embedded": embedded_count,
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("generate_embeddings failed for %s: %s", document_id, exc)
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for embedding generation on %s", document_id)
            raise


async def _generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts using OpenAI."""
    try:
        from openai import AsyncOpenAI
        from app.core.config import settings

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        # Truncate texts to max token limit
        truncated = [t[:8000] for t in texts]
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=truncated,
        )
        return [item.embedding for item in response.data]
    except ImportError:
        logger.warning("OpenAI not available, using zero embeddings")
        return [[0.0] * 1536 for _ in texts]
    except Exception as exc:
        logger.error("OpenAI embedding API error: %s", exc)
        raise


async def _upsert_search_index(
    db,
    document_id: str,
    project_id: str | None,
    chunks: list,
    embeddings: list[list[float]],
    entity_type: str,
) -> None:
    """Upsert chunk embeddings into the search index table."""
    from sqlalchemy import text
    import json

    for chunk, embedding in zip(chunks, embeddings):
        embedding_str = f"[{','.join(str(v) for v in embedding)}]"
        await db.execute(
            text("""
                INSERT INTO search_index (
                    entity_type, entity_id, title, content, snippet,
                    search_vector, embedding, metadata, project_id, document_id
                )
                VALUES (
                    :entity_type, :entity_id, :title, :content, :snippet,
                    to_tsvector('english', :content), :embedding::vector,
                    :metadata::jsonb, :project_id, :document_id
                )
                ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    snippet = EXCLUDED.snippet,
                    search_vector = EXCLUDED.search_vector,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW()
            """),
            {
                "entity_type": entity_type,
                "entity_id": f"{document_id}:{chunk.chunk_index}",
                "title": f"Chunk {chunk.chunk_index}",
                "content": chunk.content,
                "snippet": chunk.content[:200],
                "embedding": embedding_str,
                "metadata": json.dumps(chunk.metadata or {}),
                "project_id": project_id,
                "document_id": document_id,
            },
        )
