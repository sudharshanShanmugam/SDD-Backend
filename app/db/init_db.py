"""Database initialisation: create tables and seed the first super-user + default workspace."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import OrgPlan, UserRole
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.session import get_engine

logger = get_logger(__name__)

# ── Fixed seed UUIDs (must match frontend DEV_USER / DEV_ORG constants) ─────
# frontend/src/store/authStore.ts  →  DEV_USER.id / DEV_ORG.id
SEED_USER_UUID      = uuid.UUID("00000000-0000-0000-0000-000000000001")
SEED_ORG_UUID       = uuid.UUID("00000000-0000-0000-0000-000000000020")
SEED_WORKSPACE_UUID = uuid.UUID("00000000-0000-0000-0000-000000000030")
SEED_MEMBER_UUID    = uuid.UUID("00000000-0000-0000-0000-000000000040")
SEED_WS_MEMBER_UUID = uuid.UUID("00000000-0000-0000-0000-000000000041")


async def create_tables() -> None:
    """Create all tables that don't already exist (dev/test only)."""
    from app.db.base import Base  # noqa: F401 – ensures all models loaded

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")


async def init_db(db: AsyncSession) -> None:
    """Seed initial data: platform organisation + super-admin user + default workspace."""
    from app.models.organization import Organization, OrganizationMember
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember
    from sqlalchemy import select

    now = datetime.now(tz=timezone.utc)

    # ── Guard: skip if superuser already exists ─────────────────────────────
    result = await db.execute(
        select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)
    )
    existing = result.scalars().first()
    if existing:
        logger.info("Superuser already exists, skipping seed", email=settings.FIRST_SUPERUSER_EMAIL)
        # Still ensure the workspace exists for returning users
        await _ensure_default_workspace(db, now)
        return

    # ── Create platform organisation (fixed UUID = frontend DEV_ORG.id) ─────
    org = Organization(
        id=SEED_ORG_UUID,
        name="My Organization",
        slug="my-org",
        plan=OrgPlan.ENTERPRISE,
        is_active=True,
        settings={},
        created_at=now,
        updated_at=now,
    )
    db.add(org)
    await db.flush()

    # ── Create super-admin user (fixed UUID = frontend DEV_USER.id) ──────────
    user = User(
        id=SEED_USER_UUID,
        email=settings.FIRST_SUPERUSER_EMAIL,
        full_name=settings.FIRST_SUPERUSER_NAME,
        hashed_password=hash_password(settings.FIRST_SUPERUSER_PASSWORD),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
        is_verified=True,
        organization_id=SEED_ORG_UUID,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.flush()

    # ── Associate user ↔ org ─────────────────────────────────────────────────
    member = OrganizationMember(
        id=SEED_MEMBER_UUID,
        organization_id=SEED_ORG_UUID,
        user_id=SEED_USER_UUID,
        role=UserRole.ORG_ADMIN,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(member)
    await db.flush()

    # ── Create default workspace ─────────────────────────────────────────────
    workspace = Workspace(
        id=SEED_WORKSPACE_UUID,
        organization_id=SEED_ORG_UUID,
        name="Default Workspace",
        slug="default",
        description="Your first workspace",
        color="#6366f1",
        is_active=True,
        is_default=True,
        settings={},
        created_by=SEED_USER_UUID,
        created_at=now,
        updated_at=now,
    )
    db.add(workspace)
    await db.flush()

    # ── Add user as workspace admin ──────────────────────────────────────────
    ws_member = WorkspaceMember(
        id=SEED_WS_MEMBER_UUID,
        workspace_id=SEED_WORKSPACE_UUID,
        user_id=SEED_USER_UUID,
        role=UserRole.ORG_ADMIN,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(ws_member)

    await db.commit()
    logger.info(
        "Database seeded",
        superuser_email=settings.FIRST_SUPERUSER_EMAIL,
        org_id=str(SEED_ORG_UUID),
        workspace_id=str(SEED_WORKSPACE_UUID),
    )


async def _ensure_default_workspace(db: AsyncSession, now: datetime) -> None:
    """Idempotently create the default workspace if it was never seeded."""
    from app.models.workspace import Workspace, WorkspaceMember
    from app.models.user import User
    from sqlalchemy import select

    # Check if workspace already exists
    result = await db.execute(
        select(Workspace).where(Workspace.id == SEED_WORKSPACE_UUID)
    )
    if result.scalars().first():
        return  # Already exists

    # Find the org's first user to use as created_by
    user_result = await db.execute(
        select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)
    )
    user = user_result.scalars().first()
    if not user:
        return

    workspace = Workspace(
        id=SEED_WORKSPACE_UUID,
        organization_id=user.organization_id,
        name="Default Workspace",
        slug="default",
        description="Your first workspace",
        color="#6366f1",
        is_active=True,
        is_default=True,
        settings={},
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(workspace)

    ws_member = WorkspaceMember(
        id=SEED_WS_MEMBER_UUID,
        workspace_id=SEED_WORKSPACE_UUID,
        user_id=user.id,
        role=UserRole.ORG_ADMIN,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(ws_member)
    await db.commit()
    logger.info("Default workspace created retroactively", workspace_id=str(SEED_WORKSPACE_UUID))


async def verify_db_connection(db: AsyncSession) -> bool:
    """Check that the database is reachable."""
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database connection check failed", error=str(exc))
        return False
