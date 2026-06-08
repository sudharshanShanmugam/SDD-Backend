"""
Celery application configuration.
Redis broker, result backend, task routing, rate limiting, retry policies.
"""
import logging
import os

from celery import Celery
from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    worker_ready,
    worker_shutdown,
)
from kombu import Exchange, Queue

logger = logging.getLogger(__name__)

# ── Application factory ────────────────────────────────────────────────────────

def create_celery_app() -> Celery:
    broker_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    result_backend = os.environ.get("CELERY_RESULT_BACKEND", broker_url)

    app = Celery(
        "sdd_worker",
        broker=broker_url,
        backend=result_backend,
        include=[
            "app.workers.tasks.document_tasks",
            "app.workers.tasks.ai_tasks",
            "app.workers.tasks.notification_tasks",
            "app.workers.tasks.maintenance_tasks",
        ],
    )

    # ── Broker settings ────────────────────────────────────────────────────
    app.conf.broker_connection_retry_on_startup = True
    app.conf.broker_connection_max_retries = 10
    app.conf.broker_heartbeat = 10
    app.conf.broker_pool_limit = 10

    # ── Result backend ─────────────────────────────────────────────────────
    app.conf.result_expires = 86400  # 24 hours
    app.conf.result_compression = "gzip"
    app.conf.result_serializer = "json"

    # ── Task serialization ─────────────────────────────────────────────────
    app.conf.task_serializer = "json"
    app.conf.accept_content = ["json"]
    app.conf.timezone = "UTC"
    app.conf.enable_utc = True

    # ── Task execution ─────────────────────────────────────────────────────
    app.conf.task_track_started = True
    app.conf.task_acks_late = True          # Ack after task completes (better reliability)
    app.conf.worker_prefetch_multiplier = 1  # Prevents starving slow queues
    app.conf.task_reject_on_worker_lost = True
    app.conf.task_soft_time_limit = 300     # 5 min soft limit
    app.conf.task_time_limit = 600          # 10 min hard limit

    # ── Default retry policy ───────────────────────────────────────────────
    app.conf.task_default_retry_delay = 30   # seconds
    app.conf.task_max_retries = 3

    # ── Queues and routing ─────────────────────────────────────────────────
    default_exchange = Exchange("default", type="direct")
    ai_exchange = Exchange("ai", type="direct")
    priority_exchange = Exchange("priority", type="direct")

    app.conf.task_queues = (
        Queue("default", default_exchange, routing_key="default", max_priority=5),
        Queue("documents", default_exchange, routing_key="documents", max_priority=5),
        Queue("ai", ai_exchange, routing_key="ai", max_priority=10),
        Queue("notifications", default_exchange, routing_key="notifications", max_priority=8),
        Queue("maintenance", default_exchange, routing_key="maintenance", max_priority=2),
        Queue("priority", priority_exchange, routing_key="priority", max_priority=10),
    )

    app.conf.task_default_queue = "default"
    app.conf.task_default_exchange = "default"
    app.conf.task_default_routing_key = "default"

    app.conf.task_routes = {
        # Document tasks → documents queue
        "app.workers.tasks.document_tasks.process_document": {"queue": "documents"},
        "app.workers.tasks.document_tasks.generate_embeddings": {"queue": "documents"},
        # AI tasks → ai queue (higher concurrency allowed)
        "app.workers.tasks.ai_tasks.*": {"queue": "ai"},
        # Notification tasks → notifications queue
        "app.workers.tasks.notification_tasks.*": {"queue": "notifications"},
        # Maintenance → low-priority queue
        "app.workers.tasks.maintenance_tasks.*": {"queue": "maintenance"},
    }

    # ── Rate limiting ──────────────────────────────────────────────────────
    # Per-worker rate limiting: tokens consumed at task start
    app.conf.task_annotations = {
        "app.workers.tasks.ai_tasks.run_requirement_extraction": {
            "rate_limit": "10/m",
            "max_retries": 3,
            "default_retry_delay": 60,
            "soft_time_limit": 600,
            "time_limit": 900,
        },
        "app.workers.tasks.ai_tasks.generate_epics": {
            "rate_limit": "20/m",
        },
        "app.workers.tasks.document_tasks.process_document": {
            "rate_limit": "30/m",
            "max_retries": 3,
            "default_retry_delay": 30,
        },
        "app.workers.tasks.document_tasks.generate_embeddings": {
            "rate_limit": "20/m",
        },
        "app.workers.tasks.notification_tasks.send_broadcast": {
            "rate_limit": "5/m",
        },
    }

    # ── Worker pool ────────────────────────────────────────────────────────
    app.conf.worker_concurrency = int(os.environ.get("CELERY_CONCURRENCY", "4"))
    app.conf.worker_max_tasks_per_child = 200    # Recycle after N tasks (memory leak prevention)
    app.conf.worker_disable_rate_limits = False

    # ── Monitoring ─────────────────────────────────────────────────────────
    app.conf.worker_send_task_events = True
    app.conf.task_send_sent_event = True

    # ── Free-tier mode: run tasks synchronously in the web process ─────────
    # Default True so tasks work on Render free plan without a separate worker.
    # Set CELERY_TASK_ALWAYS_EAGER=false explicitly to use a real worker.
    eager = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "true").lower() not in ("false", "0")
    if eager:
        app.conf.task_always_eager = True
        app.conf.task_eager_propagates = True

    return app


celery_app = create_celery_app()


# ── Signal handlers ────────────────────────────────────────────────────────────

@worker_ready.connect
def on_worker_ready(sender=None, **kwargs):
    logger.info("Celery worker ready. Queues: %s", list(celery_app.conf.task_queues))


@worker_shutdown.connect
def on_worker_shutdown(sender=None, **kwargs):
    logger.info("Celery worker shutting down.")


@task_prerun.connect
def on_task_prerun(task_id=None, task=None, args=None, kwargs=None, **extra):
    logger.debug("Task starting: %s [%s]", task.name, task_id)


@task_postrun.connect
def on_task_postrun(task_id=None, task=None, state=None, retval=None, **extra):
    logger.debug("Task finished: %s [%s] state=%s", task.name, task_id, state)


@task_failure.connect
def on_task_failure(task_id=None, exception=None, traceback=None, sender=None, **extra):
    logger.error(
        "Task FAILED: %s [%s] exception=%s",
        sender.name if sender else "unknown",
        task_id,
        exception,
        exc_info=True,
    )


# ── Context manager for database sessions in tasks ────────────────────────────

from contextlib import asynccontextmanager
from typing import AsyncGenerator


@asynccontextmanager
async def get_db_session() -> AsyncGenerator:
    """
    Async context manager yielding a fresh DB session for Celery tasks.
    Creates a new engine per call so it's bound to the current event loop
    (Celery fork workers inherit a dead parent-process loop otherwise).
    """
    import os
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://sdd_user:sdd_password@localhost:5432/sdd_platform",
    )
    engine = create_async_engine(db_url, echo=False, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await engine.dispose()


def run_async(coro):
    """
    Run an async coroutine from a sync Celery task.
    Always creates a fresh event loop — Celery fork workers inherit a closed loop.
    """
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
