"""
Notification Celery tasks.
Email notifications, push notifications, broadcast messaging.
"""
import logging
from datetime import datetime, timezone

from app.workers.celery_app import celery_app, get_db_session, run_async

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.tasks.notification_tasks.send_email",
    max_retries=3,
    default_retry_delay=60,
    queue="notifications",
)
def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    from_name: str = "SDD Platform",
) -> dict:
    """
    Send a single transactional email via configured email provider.
    Supports SendGrid and SES via SMTP fallback.
    """
    async def _run():
        try:
            from app.core.config import settings

            if settings.EMAIL_PROVIDER == "sendgrid":
                return await _send_via_sendgrid(
                    to_email=to_email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    from_name=from_name,
                )
            elif settings.EMAIL_PROVIDER == "ses":
                return await _send_via_ses(
                    to_email=to_email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                )
            else:
                return await _send_via_smtp(
                    to_email=to_email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                )
        except Exception as exc:
            logger.error("Email send failed to %s: %s", to_email, exc)
            raise

    return run_async(_run())


@celery_app.task(
    name="app.workers.tasks.notification_tasks.send_broadcast",
    max_retries=2,
    queue="notifications",
    rate_limit="5/m",
)
def send_broadcast(
    user_ids: list[str],
    title: str,
    message: str,
    severity: str = "info",
) -> dict:
    """
    Send a broadcast notification to multiple users.
    Creates in-app notifications and optionally sends emails.
    """
    async def _run():
        async with get_db_session() as db:
            if db is None:
                return {"sent": 0}

            from app.services.notification_service import NotificationService
            svc = NotificationService(db)

            sent = 0
            batch_size = 100

            for i in range(0, len(user_ids), batch_size):
                batch = user_ids[i : i + batch_size]
                for user_id in batch:
                    try:
                        await svc.create_notification(
                            user_id=user_id,
                            title=title,
                            message=message,
                            notification_type="broadcast",
                            metadata={"severity": severity},
                        )
                        sent += 1
                    except Exception as exc:
                        logger.warning("Failed to create notification for user %s: %s", user_id, exc)

            logger.info("Broadcast sent to %d/%d users", sent, len(user_ids))
            return {
                "sent": sent,
                "total": len(user_ids),
                "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            }

    return run_async(_run())


@celery_app.task(
    name="app.workers.tasks.notification_tasks.send_digest",
    queue="notifications",
)
def send_digest(user_id: str) -> dict:
    """
    Send the notification digest email for a user.
    Collects unread notifications and formats a digest email.
    """
    async def _run():
        async with get_db_session() as db:
            if db is None:
                return {"sent": False}

            from app.services.notification_service import NotificationService
            from app.services.user_service import UserService

            notif_svc = NotificationService(db)
            user_svc = UserService(db)

            user = await user_svc.get_by_id(user_id)
            if not user:
                return {"sent": False, "reason": "user_not_found"}

            prefs = await notif_svc.get_preferences(user_id)
            if not prefs or not getattr(prefs, "digest_enabled", False):
                return {"sent": False, "reason": "digest_disabled"}

            # Get unread notifications
            notifs = await notif_svc.list_notifications(
                user_id=user_id,
                is_read=False,
                notification_type=None,
                page=1,
                page_size=50,
            )

            if not notifs["items"]:
                return {"sent": False, "reason": "no_unread_notifications"}

            # Build digest HTML
            items_html = "".join(
                f"<li><strong>{n.title}</strong>: {n.message}</li>"
                for n in notifs["items"]
            )
            html_body = f"""
            <html>
            <body>
                <h2>Your SDD Platform Digest</h2>
                <p>You have {notifs['total']} unread notification(s):</p>
                <ul>{items_html}</ul>
                <p><a href="{_get_frontend_url()}/notifications">View all notifications</a></p>
            </body>
            </html>
            """

            send_email.delay(
                to_email=user.email,
                subject=f"SDD Digest: {notifs['total']} new notification(s)",
                html_body=html_body,
            )

            return {
                "sent": True,
                "notification_count": notifs["total"],
                "user_id": user_id,
            }

    return run_async(_run())


# ── Email provider implementations ────────────────────────────────────────────

async def _send_via_sendgrid(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None,
    from_name: str,
) -> dict:
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, To
        from app.core.config import settings

        sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
        message = Mail(
            from_email=(settings.FROM_EMAIL, from_name),
            to_emails=[To(to_email)],
            subject=subject,
            html_content=html_body,
            plain_text_content=text_body or "",
        )
        response = sg.send(message)
        logger.info("Email sent via SendGrid to %s (status=%s)", to_email, response.status_code)
        return {"provider": "sendgrid", "status": response.status_code}
    except ImportError:
        logger.warning("sendgrid package not installed, falling back to SMTP")
        return await _send_via_smtp(to_email, subject, html_body, text_body)


async def _send_via_ses(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None,
) -> dict:
    try:
        import aioboto3
        from app.core.config import settings

        session = aioboto3.Session()
        async with session.client("ses", region_name=settings.AWS_REGION) as ses:
            await ses.send_email(
                Source=settings.FROM_EMAIL,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {
                        "Html": {"Data": html_body},
                        **({"Text": {"Data": text_body}} if text_body else {}),
                    },
                },
            )
        logger.info("Email sent via SES to %s", to_email)
        return {"provider": "ses", "status": "sent"}
    except Exception as exc:
        logger.error("SES send failed: %s", exc)
        raise


async def _send_via_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None,
) -> dict:
    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from app.core.config import settings

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.FROM_EMAIL
        msg["To"] = to_email

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_USE_TLS,
        )
        logger.info("Email sent via SMTP to %s", to_email)
        return {"provider": "smtp", "status": "sent"}
    except ImportError:
        logger.warning("aiosmtplib not installed, email not sent")
        return {"provider": "none", "status": "skipped"}
    except Exception as exc:
        logger.error("SMTP send failed: %s", exc)
        raise


def _get_frontend_url() -> str:
    try:
        from app.core.config import settings
        return settings.FRONTEND_URL
    except Exception:
        return "http://localhost:3000"
