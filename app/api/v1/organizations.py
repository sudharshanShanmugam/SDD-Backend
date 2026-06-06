"""
Organization management API routes.
Org CRUD, member management, invitations.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.services.organization_service import OrganizationService

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$", max_length=100)
    description: str | None = None
    logo_url: str | None = None
    website: str | None = None


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    logo_url: str | None = None
    website: str | None = None
    settings: dict | None = None


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern="^(admin|member|viewer)$")


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(pattern="^(admin|member|viewer)$")


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    logo_url: str | None
    website: str | None
    member_count: int
    created_at: str

    class Config:
        from_attributes = True


class MemberResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    avatar_url: str | None
    role: str
    joined_at: str

    class Config:
        from_attributes = True


class InviteResponse(BaseModel):
    id: str
    email: str
    role: str
    invited_by: str
    expires_at: str
    status: str

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create organization",
)
async def create_organization(
    payload: OrganizationCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new organization. The creator becomes the owner."""
    svc = OrganizationService(db)
    return await svc.create_organization(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        logo_url=payload.logo_url,
        website=payload.website,
        owner_id=str(current_user.id),
    )


@router.get(
    "",
    summary="List organizations for current user",
)
async def list_organizations(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all organizations the current user belongs to."""
    svc = OrganizationService(db)
    return await svc.list_user_organizations(user_id=str(current_user.id))


@router.get(
    "/{org_id}",
    summary="Get organization details",
)
async def get_organization(
    org_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get organization details. Requires membership."""
    svc = OrganizationService(db)
    await svc.assert_member(org_id=org_id, user_id=str(current_user.id))
    org_data = await svc.get_serialized(org_id)
    if not org_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    return org_data


@router.patch(
    "/{org_id}",
    summary="Update organization",
)
async def update_organization(
    org_id: str,
    payload: OrganizationUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update organization details. Requires admin role."""
    svc = OrganizationService(db)
    await svc.assert_admin(org_id=org_id, user_id=str(current_user.id))
    return await svc.update_organization(
        org_id=org_id,
        data=payload.model_dump(exclude_none=True),
    )


@router.delete(
    "/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete organization",
)
async def delete_organization(
    org_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete an organization. Owner only."""
    svc = OrganizationService(db)
    await svc.assert_owner(org_id=org_id, user_id=str(current_user.id))
    await svc.delete_organization(org_id=org_id)


@router.get(
    "/{org_id}/members",
    summary="List organization members",
)
async def list_members(
    org_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all members of an organization."""
    svc = OrganizationService(db)
    await svc.assert_member(org_id=org_id, user_id=str(current_user.id))
    return await svc.list_members(org_id=org_id, page=page, page_size=page_size)


@router.post(
    "/{org_id}/members/invite",
    status_code=status.HTTP_201_CREATED,
    summary="Invite user to organization",
)
async def invite_member(
    org_id: str,
    payload: InviteMemberRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send an invitation email to add a user to the organization."""
    svc = OrganizationService(db)
    await svc.assert_admin(org_id=org_id, user_id=str(current_user.id))

    invite = await svc.create_invite(
        org_id=org_id,
        email=payload.email,
        role=payload.role,
        invited_by=str(current_user.id),
    )

    background_tasks.add_task(
        svc.send_invite_email,
        invite_id=invite.get("id", ""),
        inviter_name=current_user.full_name,
    )

    return invite


@router.post(
    "/invites/{token}/accept",
    status_code=status.HTTP_200_OK,
    summary="Accept organization invitation",
)
async def accept_invite(
    token: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept an invitation to join an organization."""
    svc = OrganizationService(db)
    result = await svc.accept_invite(token=token, user_id=str(current_user.id))
    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation.",
        )
    return {"message": "Successfully joined the organization."}


@router.patch(
    "/{org_id}/members/{user_id}/role",
    summary="Update member role",
)
async def update_member_role(
    org_id: str,
    user_id: str,
    payload: UpdateMemberRoleRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change a member's role within the organization. Admin only."""
    svc = OrganizationService(db)
    await svc.assert_admin(org_id=org_id, user_id=str(current_user.id))
    updated = await svc.update_member_role(
        org_id=org_id,
        user_id=user_id,
        role=payload.role,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    return {"message": "Role updated successfully.", "user_id": user_id, "role": payload.role}


@router.delete(
    "/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove member from organization",
)
async def remove_member(
    org_id: str,
    user_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from the organization. Admin only, or self-removal."""
    svc = OrganizationService(db)
    if str(current_user.id) != user_id:
        await svc.assert_admin(org_id=org_id, user_id=str(current_user.id))
    await svc.remove_member(org_id=org_id, user_id=user_id)
