"""
Background task runner for free-tier deployments (no Celery worker).

Runs Celery tasks in daemon threads and stores results directly in Redis
using the same key format Celery uses (`celery-task-meta-{task_id}`),
so existing AsyncResult polling keeps working unchanged.
"""
import json
import threading
import uuid as _uuid
from typing import Any, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)


def _store_result(task_id: str, state: str, result: Any = None, error: str | None = None) -> None:
    """Write task state into Redis in Celery's native result format."""
    try:
        import redis as _redis
        import os
        r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        payload = {
            "status": state,
            "result": result,
            "traceback": error,
            "children": [],
            "task_id": task_id,
        }
        r.set(f"celery-task-meta-{task_id}", json.dumps(payload), ex=86400)
    except Exception as exc:
        logger.warning("runner: failed to store task result in Redis", task_id=task_id, error=str(exc))


def run_in_background(task_func: Callable, task_id: str | None = None, **kwargs: Any) -> str:
    """
    Dispatch `task_func` to a daemon thread and return a task_id immediately.

    Compatible with Celery's AsyncResult polling: stores PENDING → SUCCESS/FAILURE
    in Redis under the standard `celery-task-meta-{task_id}` key.
    """
    if task_id is None:
        task_id = str(_uuid.uuid4())

    _store_result(task_id, "PENDING")

    def _run() -> None:
        try:
            _store_result(task_id, "STARTED")
            result = task_func(**kwargs)
            _store_result(task_id, "SUCCESS", result=result)
            logger.info("runner: task completed", task_id=task_id)
        except Exception as exc:
            logger.exception("runner: task failed", task_id=task_id, error=str(exc))
            _store_result(task_id, "FAILURE", error=str(exc))

    thread = threading.Thread(target=_run, daemon=True, name=f"bg-task-{task_id[:8]}")
    thread.start()
    return task_id
