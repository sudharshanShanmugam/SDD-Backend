"""
Celery Beat schedule configuration.
Periodic task schedule for maintenance and automation.
"""
from celery.schedules import crontab

from app.workers.celery_app import celery_app

celery_app.conf.beat_schedule = {
    # ── Token maintenance ──────────────────────────────────────────────────
    "cleanup-expired-tokens": {
        "task": "app.workers.tasks.maintenance_tasks.cleanup_expired_tokens",
        "schedule": crontab(minute=0, hour="*/6"),  # Every 6 hours
        "options": {"queue": "maintenance"},
    },

    # ── Search index ───────────────────────────────────────────────────────
    "rebuild-search-index-weekly": {
        "task": "app.workers.tasks.maintenance_tasks.rebuild_search_index",
        "schedule": crontab(minute=0, hour=2, day_of_week="sunday"),  # Sunday 2 AM
        "options": {"queue": "maintenance"},
    },

    # ── Notification digests ───────────────────────────────────────────────
    "send-daily-digests": {
        "task": "app.workers.tasks.maintenance_tasks.send_digest_emails",
        "schedule": crontab(minute=0, hour=8),  # Daily at 8 AM UTC
        "options": {"queue": "maintenance"},
    },

    # ── Notification cleanup ───────────────────────────────────────────────
    "cleanup-old-notifications": {
        "task": "app.workers.tasks.maintenance_tasks.cleanup_old_notifications",
        "schedule": crontab(minute=30, hour=1),  # Daily at 1:30 AM UTC
        "kwargs": {"days": 90},
        "options": {"queue": "maintenance"},
    },

    # ── Database maintenance ───────────────────────────────────────────────
    "vacuum-database": {
        "task": "app.workers.tasks.maintenance_tasks.vacuum_database",
        "schedule": crontab(minute=0, hour=3, day_of_week="saturday"),  # Saturday 3 AM
        "options": {"queue": "maintenance"},
    },

    # ── Document retry ─────────────────────────────────────────────────────
    "retry-failed-documents": {
        "task": "app.workers.tasks.maintenance_tasks.retry_failed_documents",
        "schedule": crontab(minute="*/30"),  # Every 30 minutes
        "options": {"queue": "maintenance"},
    },
}

celery_app.conf.beat_scheduler = "celery.beat:PersistentScheduler"
celery_app.conf.beat_schedule_filename = "/tmp/celerybeat-schedule"
