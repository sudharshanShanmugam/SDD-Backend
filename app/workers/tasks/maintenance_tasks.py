"""
Maintenance Celery tasks.
Token cleanup, search index rebuild, database vacuuming, digest sending.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import celery_app, get_db_session, run_async

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.tasks.maintenance_tasks.cleanup_expired_tokens",
    queue="maintenance",
)
def cleanup_expired_tokens() -> dict:
    """
    Remove expired refresh tokens and purge old blacklisted access tokens from Redis.
    This task runs periodically (see beats.py).
    """
    async def _run():
        deleted = 0
        try:
            from app.services.auth_service import get_redis

            redis = await get_redis()
            # Scan for refresh token keys
            cursor = 0
            pattern = "refresh:*"
            while True:
                cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=500)
                for key in keys:
                    ttl = await redis.ttl(key)
                    if ttl == -1:  # No expiry set — shouldn't happen, clean up
                        await redis.delete(key)
                        deleted += 1
                if cursor == 0:
                    break

            logger.info("Token cleanup complete: %d stale tokens removed", deleted)
        except Exception as exc:
            logger.error("Token cleanup failed: %s", exc)

        return {
            "deleted_tokens": deleted,
            "completed_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    return run_async(_run())


@celery_app.task(
    name="app.workers.tasks.maintenance_tasks.rebuild_search_index",
    queue="maintenance",
    soft_time_limit=1800,
    time_limit=2400,
)
def rebuild_search_index() -> dict:
    """
    Rebuild the full-text search index and re-embed all searchable entities.
    This is a heavy operation; run during off-peak hours.
    """
    async def _run():
        async with get_db_session() as db:
            if db is None:
                return {"status": "skipped", "reason": "db_unavailable"}

            indexed = {"requirements": 0, "epics": 0, "stories": 0, "tasks": 0}

            try:
                from sqlalchemy import text

                # Refresh full-text search vectors for requirements
                await db.execute(
                    text("""
                        INSERT INTO search_index (entity_type, entity_id, title, content, snippet, search_vector, project_id)
                        SELECT
                            'requirement',
                            id::text,
                            title,
                            COALESCE(description, ''),
                            LEFT(COALESCE(description, ''), 200),
                            to_tsvector('english', title || ' ' || COALESCE(description, '')),
                            project_id::text
                        FROM requirements
                        ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                            title = EXCLUDED.title,
                            content = EXCLUDED.content,
                            search_vector = EXCLUDED.search_vector,
                            updated_at = NOW()
                    """)
                )

                await db.execute(
                    text("""
                        INSERT INTO search_index (entity_type, entity_id, title, content, snippet, search_vector, project_id)
                        SELECT
                            'epic',
                            id::text,
                            title,
                            COALESCE(description, ''),
                            LEFT(COALESCE(description, ''), 200),
                            to_tsvector('english', title || ' ' || COALESCE(description, '')),
                            project_id::text
                        FROM epics
                        ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                            title = EXCLUDED.title,
                            content = EXCLUDED.content,
                            search_vector = EXCLUDED.search_vector,
                            updated_at = NOW()
                    """)
                )

                await db.execute(
                    text("""
                        INSERT INTO search_index (entity_type, entity_id, title, content, snippet, search_vector, project_id)
                        SELECT
                            'story',
                            id::text,
                            title,
                            COALESCE(description, ''),
                            LEFT(COALESCE(description, ''), 200),
                            to_tsvector('english', title || ' ' || COALESCE(description, '')),
                            project_id::text
                        FROM stories
                        ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                            title = EXCLUDED.title,
                            content = EXCLUDED.content,
                            search_vector = EXCLUDED.search_vector,
                            updated_at = NOW()
                    """)
                )

                await db.execute(text("ANALYZE search_index"))
                logger.info("Search index rebuilt")
            except Exception as exc:
                logger.error("Search index rebuild failed: %s", exc)
                return {"status": "failed", "error": str(exc)}

            return {
                "status": "completed",
                "indexed": indexed,
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }

    return run_async(_run())


@celery_app.task(
    name="app.workers.tasks.maintenance_tasks.send_digest_emails",
    queue="maintenance",
)
def send_digest_emails() -> dict:
    """
    Send notification digest emails to all users with digests enabled.
    Runs daily or weekly based on user preferences.
    """
    async def _run():
        async with get_db_session() as db:
            if db is None:
                return {"queued": 0}

            try:
                from sqlalchemy import select
                from app.models.notification import NotificationPreferences

                result = await db.execute(
                    select(NotificationPreferences.user_id).where(
                        NotificationPreferences.digest_enabled == True
                    )
                )
                user_ids = [str(row[0]) for row in result.all()]

                from app.workers.tasks.notification_tasks import send_digest
                for uid in user_ids:
                    send_digest.delay(uid)

                logger.info("Digest emails queued for %d users", len(user_ids))
                return {"queued": len(user_ids)}
            except Exception as exc:
                logger.error("Digest email scheduling failed: %s", exc)
                return {"queued": 0, "error": str(exc)}

    return run_async(_run())


@celery_app.task(
    name="app.workers.tasks.maintenance_tasks.cleanup_old_notifications",
    queue="maintenance",
)
def cleanup_old_notifications(days: int = 90) -> dict:
    """Remove read notifications older than N days."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                return {"deleted": 0}

            cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
            try:
                from sqlalchemy import delete, text
                result = await db.execute(
                    text("""
                        DELETE FROM notifications
                        WHERE is_read = true
                        AND created_at < :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                count = result.rowcount
                logger.info("Cleaned up %d old notifications", count)
                return {
                    "deleted": count,
                    "cutoff_date": cutoff.isoformat(),
                    "completed_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            except Exception as exc:
                logger.error("Notification cleanup failed: %s", exc)
                return {"deleted": 0, "error": str(exc)}

    return run_async(_run())


@celery_app.task(
    name="app.workers.tasks.maintenance_tasks.vacuum_database",
    queue="maintenance",
)
def vacuum_database() -> dict:
    """Run VACUUM ANALYZE on heavily-written tables for performance maintenance."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                return {"status": "skipped"}

            tables = [
                "audit_logs",
                "notifications",
                "search_index",
                "ai_generations",
            ]
            vacuumed = []
            from sqlalchemy import text
            from sqlalchemy.exc import OperationalError

            for table in tables:
                try:
                    # VACUUM requires autocommit mode
                    await db.execute(text("COMMIT"))
                    await db.execute(text(f"VACUUM ANALYZE {table}"))
                    vacuumed.append(table)
                except OperationalError as exc:
                    logger.warning("VACUUM failed for %s: %s", table, exc)
                except Exception as exc:
                    logger.warning("Unexpected error vacuuming %s: %s", table, exc)

            logger.info("Database vacuum complete: %s", vacuumed)
            return {
                "vacuumed_tables": vacuumed,
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }

    return run_async(_run())


@celery_app.task(
    name="app.workers.tasks.maintenance_tasks.retry_failed_documents",
    queue="maintenance",
)
def retry_failed_documents() -> dict:
    """Re-queue failed documents that are eligible for reprocessing."""
    async def _run():
        async with get_db_session() as db:
            if db is None:
                return {"retried": 0}

            from sqlalchemy import select, text
            from datetime import datetime, timedelta, timezone

            # Only retry documents that failed within the last 24 hours
            cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)

            try:
                result = await db.execute(
                    text("""
                        SELECT id FROM documents
                        WHERE status = 'failed'
                        AND updated_at > :cutoff
                        AND retry_count < 3
                        LIMIT 50
                    """),
                    {"cutoff": cutoff},
                )
                doc_ids = [str(row[0]) for row in result.all()]

                from app.workers.tasks.document_tasks import process_document
                for doc_id in doc_ids:
                    process_document.delay(doc_id)

                if doc_ids:
                    await db.execute(
                        text("""
                            UPDATE documents
                            SET retry_count = retry_count + 1, status = 'pending'
                            WHERE id = ANY(:ids)
                        """),
                        {"ids": doc_ids},
                    )

                logger.info("Retried %d failed documents", len(doc_ids))
                return {
                    "retried": len(doc_ids),
                    "completed_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            except Exception as exc:
                logger.error("Document retry task failed: %s", exc)
                return {"retried": 0, "error": str(exc)}

    return run_async(_run())
