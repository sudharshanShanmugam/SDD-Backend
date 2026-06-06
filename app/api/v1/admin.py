"""
Admin console API routes.
System administration, platform metrics, config management.
"""
import logging
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_admin, require_superadmin
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter()


class SystemConfigUpdate(BaseModel):
    key: str
    value: str
    description: str | None = None


class BroadcastMessageRequest(BaseModel):
    title: str
    message: str
    severity: str = "info"
    target: str = "all"


class CreateUserRequest(BaseModel):
    email: EmailStr
    firstName: str
    lastName: str
    role: str = "developer"
    organization: str | None = None


@router.get(
    "/stats",
    summary="Get platform-wide statistics",
)
async def get_platform_stats(
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return platform-level stats: user counts, storage usage, AI quota."""
    from app.services.analytics_service import AnalyticsService
    svc = AnalyticsService(db)
    return await svc.get_platform_stats()


@router.get(
    "/users",
    summary="Admin user list with full details",
)
async def admin_list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
    role: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all platform users with admin details."""
    svc = UserService(db)
    return await svc.list_users(
        page=page,
        page_size=page_size,
        search=search,
        role=role,
        is_active=is_active,
    )


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a new user",
)
async def admin_create_user(
    payload: CreateUserRequest,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a user directly — no invitation email is sent. A temporary password
    is set; the user can reset it via Forgot Password on first login."""
    svc = UserService(db)

    existing = await svc.get_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    alphabet = string.ascii_letters + string.digits + "!@#$%"
    temp_password = "".join(secrets.choice(alphabet) for _ in range(16))

    full_name = f"{payload.firstName} {payload.lastName}".strip()
    user = await svc.create_user(
        email=payload.email,
        password=temp_password,
        full_name=full_name,
        role=payload.role,
    )

    # Add user to the selected organisation if an org ID was provided
    if payload.organization:
        from app.models.organization import OrganizationMember
        from app.core.constants import UserRole as UR
        import uuid as _uuid
        try:
            org_member = OrganizationMember(
                id=_uuid.uuid4(),
                organization_id=_uuid.UUID(payload.organization),
                user_id=user.id,
                role=UR(payload.role) if payload.role in [r.value for r in UR] else UR.VIEWER,
                is_active=True,
            )
            db.add(org_member)
            await db.commit()
        except Exception:
            pass  # Org ID may be invalid; user is still created
    return {
        "id": str(user.id),
        "email": user.email,
        "fullName": user.full_name,
        "role": str(user.role),
        "isActive": user.is_active,
    }


@router.post(
    "/users/{user_id}/impersonate",
    summary="Impersonate user (superadmin only)",
)
async def impersonate_user(
    user_id: str,
    current_user=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Generate a short-lived impersonation token. Superadmin only."""
    from app.services.auth_service import AuthService
    auth_svc = AuthService(db)
    user_svc = UserService(db)

    target_user = await user_svc.get_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    token = auth_svc.create_access_token(
        data={
            "sub": str(target_user.id),
            "email": target_user.email,
            "role": target_user.role,
            "impersonated_by": str(current_user.id),
        },
    )
    logger.warning("Admin %s impersonating user %s", current_user.id, user_id)
    return {"access_token": token, "token_type": "bearer"}


@router.put(
    "/users/{user_id}/suspend",
    summary="Suspend a user account",
)
async def suspend_user(
    user_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = UserService(db)
    ok = await svc.deactivate_user(user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"id": user_id, "isActive": False}


@router.put(
    "/users/{user_id}/activate",
    summary="Re-activate a suspended user account",
)
async def activate_user(
    user_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = UserService(db)
    user = await svc.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await svc.update_user(user_id, {"is_active": True})
    return {"id": user_id, "isActive": True}


class EditUserRequest(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    role: str | None = None
    is_active: bool | None = None


@router.patch(
    "/users/{user_id}",
    summary="Edit a user's profile and role",
)
async def edit_user(
    user_id: str,
    payload: EditUserRequest,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = UserService(db)
    user = await svc.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    await svc.update_user(user_id, updates)
    updated = await svc.get_by_id(user_id)
    return {
        "id": str(updated.id),
        "full_name": updated.full_name,
        "email": updated.email,
        "role": updated.role,
        "is_active": updated.is_active,
    }


class BulkUserIdsRequest(BaseModel):
    ids: list[str]


@router.post(
    "/users/bulk-suspend",
    summary="Bulk suspend users",
)
async def bulk_suspend_users(
    payload: BulkUserIdsRequest,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = UserService(db)
    for uid in payload.ids:
        await svc.deactivate_user(uid)
    return {"suspended": len(payload.ids)}


@router.post(
    "/users/bulk-activate",
    summary="Bulk activate users",
)
async def bulk_activate_users(
    payload: BulkUserIdsRequest,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = UserService(db)
    for uid in payload.ids:
        await svc.update_user(uid, {"is_active": True})
    return {"activated": len(payload.ids)}


@router.get(
    "/config",
    summary="List system configuration",
)
async def list_system_config(
    current_user=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List all system configuration key-value pairs."""
    from app.services.analytics_service import AnalyticsService
    svc = AnalyticsService(db)
    return await svc.get_system_config()


@router.post(
    "/config",
    status_code=status.HTTP_201_CREATED,
    summary="Set system configuration value",
)
async def set_system_config(
    payload: SystemConfigUpdate,
    current_user=Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a system configuration value. Superadmin only."""
    from app.services.analytics_service import AnalyticsService
    svc = AnalyticsService(db)
    return await svc.set_system_config(
        key=payload.key,
        value=payload.value,
        description=payload.description,
        updated_by=str(current_user.id),
    )


@router.post(
    "/broadcast",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send broadcast notification to users",
)
async def broadcast_message(
    payload: BroadcastMessageRequest,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a broadcast notification or alert to all users or a subset."""
    from app.services.notification_service import NotificationService
    svc = NotificationService(db)
    await svc.broadcast(
        title=payload.title,
        message=payload.message,
        severity=payload.severity,
        target=payload.target,
        sent_by=str(current_user.id),
    )
    return {"message": "Broadcast queued."}


@router.post(
    "/maintenance/cleanup-tokens",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger token cleanup maintenance task",
)
async def cleanup_tokens(
    current_user=Depends(require_superadmin),
):
    """Trigger cleanup of expired refresh tokens and blacklisted access tokens."""
    from app.workers.tasks.maintenance_tasks import cleanup_expired_tokens
    task = cleanup_expired_tokens.delay()
    return {"task_id": task.id, "message": "Token cleanup triggered."}


@router.post(
    "/maintenance/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger search index rebuild",
)
async def reindex_search(
    current_user=Depends(require_superadmin),
):
    """Trigger full search index rebuild. May take several minutes."""
    from app.workers.tasks.maintenance_tasks import rebuild_search_index
    task = rebuild_search_index.delay()
    return {"task_id": task.id, "message": "Search reindex triggered."}


@router.get(
    "/organizations",
    summary="Admin: list all organizations",
)
async def admin_list_organizations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all organizations on the platform. Admin only."""
    from app.models.organization import Organization
    from sqlalchemy import select, func as sa_func
    query = select(Organization)
    if search:
        query = query.where(Organization.name.ilike(f"%{search}%"))
    total = (await db.execute(select(sa_func.count()).select_from(query.subquery()))).scalar_one()
    orgs = (await db.execute(query.order_by(Organization.created_at.desc())
                             .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {
        "items": [
            {
                "id": str(o.id),
                "name": o.name,
                "slug": o.slug,
                "plan": str(o.plan),
                "is_active": o.is_active,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orgs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.put(
    "/organizations/{org_id}/suspend",
    summary="Admin: suspend an organization",
)
async def admin_suspend_organization(
    org_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.organization import Organization
    from sqlalchemy import update as sa_update
    await db.execute(sa_update(Organization).where(Organization.id == org_id).values(is_active=False))
    await db.commit()
    return {"id": org_id, "is_active": False}


@router.put(
    "/organizations/{org_id}/activate",
    summary="Admin: activate an organization",
)
async def admin_activate_organization(
    org_id: str,
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.organization import Organization
    from sqlalchemy import update as sa_update
    await db.execute(sa_update(Organization).where(Organization.id == org_id).values(is_active=True))
    await db.commit()
    return {"id": org_id, "is_active": True}


@router.get(
    "/health",
    summary="Platform health check with component status",
)
async def platform_health(
    current_user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return health status of all platform components: DB, Redis, Celery, Search."""
    from app.services.analytics_service import AnalyticsService
    svc = AnalyticsService(db)
    return await svc.get_health_status()
