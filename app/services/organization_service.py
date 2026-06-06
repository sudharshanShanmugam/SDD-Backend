"""
Organization Service.
Organization CRUD, membership, invitations.
"""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_org(org) -> dict:
    """Serialize an Organization ORM object."""
    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "description": org.description,
        "logo_url": org.logo_url,
        "website": org.website,
        "plan": str(org.plan.value if hasattr(org.plan, "value") else org.plan),
        "is_active": org.is_active,
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None,
    }


class OrganizationService:
    """Handles organization management business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_organization(
        self,
        name: str,
        owner_id: str,
        slug: str | None = None,
        description: str | None = None,
        logo_url: str | None = None,
        website: str | None = None,
    ):
        from app.models.organization import Organization, OrganizationMember

        generated_slug = slug or self._generate_slug(name)
        # Ensure slug uniqueness
        generated_slug = await self._unique_slug(generated_slug)

        org = Organization(
            id=uuid.uuid4(),
            name=name,
            slug=generated_slug,
            description=description,
            logo_url=logo_url,
            website=website,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(org)

        # Add owner as first member
        owner_uuid = uuid.UUID(owner_id) if isinstance(owner_id, str) else owner_id
        member = OrganizationMember(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=owner_uuid,
            role="owner",
            is_active=True,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(member)

        await self.db.commit()
        await self.db.refresh(org)
        return _serialize_org(org)

    async def get_by_id(self, org_id: str):
        """Returns ORM object (for internal use and permission checks)."""
        from app.models.organization import Organization
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        return result.scalar_one_or_none()

    async def get_serialized(self, org_id: str) -> dict | None:
        """Returns serialized dict for route responses."""
        org = await self.get_by_id(org_id)
        return _serialize_org(org) if org else None

    async def list_user_organizations(self, user_id: str) -> list:
        from app.models.organization import Organization, OrganizationMember
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            return []
        result = await self.db.execute(
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user_uuid)
            .order_by(Organization.name)
        )
        return [_serialize_org(o) for o in result.scalars().all()]

    async def update_organization(self, org_id: str, data: dict):
        from app.models.organization import Organization
        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(
            update(Organization).where(Organization.id == org_id).values(**data)
        )
        await self.db.commit()
        org = await self.get_by_id(org_id)
        return _serialize_org(org) if org else None

    async def delete_organization(self, org_id: str) -> None:
        from app.models.organization import Organization
        from sqlalchemy import delete as sql_delete
        await self.db.execute(sql_delete(Organization).where(Organization.id == org_id))
        await self.db.commit()

    async def list_members(self, org_id: str, page: int = 1, page_size: int = 50) -> list:
        from app.models.organization import OrganizationMember
        from app.models.user import User
        result = await self.db.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == org_id)
            .order_by(OrganizationMember.joined_at)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = result.all()
        return [
            {
                "user_id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "avatar_url": getattr(user, "avatar_url", None),
                "role": member.role,
                "joined_at": str(member.joined_at),
            }
            for member, user in rows
        ]

    async def create_invite(
        self,
        org_id: str,
        email: str,
        role: str,
        invited_by: str,
    ) -> dict:
        """Create an invitation. Returns invite info dict (no DB table yet)."""
        import secrets
        token = secrets.token_urlsafe(32)
        invite_id = str(uuid.uuid4())
        expires_at = (datetime.now(tz=timezone.utc) + timedelta(days=7)).isoformat()

        # Log the invite (no DB table for invites yet)
        logger.info("Invite created for %s to org %s (role: %s)", email, org_id, role)

        return {
            "id": invite_id,
            "organization_id": org_id,
            "email": email.lower(),
            "role": role,
            "invited_by": invited_by,
            "token": token,
            "expires_at": expires_at,
            "status": "pending",
        }

    async def send_invite_email(self, invite_id: str, inviter_name: str) -> None:
        """Log invite email (no email service configured)."""
        logger.info("Would send invite email for invite_id=%s by %s", invite_id, inviter_name)

    async def accept_invite(self, token: str, user_id: str):
        """Accept invite - not fully implemented (no invite table)."""
        logger.warning("accept_invite called but no invite table; token=%s", token)
        return None

    async def update_member_role(self, org_id: str, user_id: str, role: str):
        from app.models.organization import OrganizationMember
        result = await self.db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            return None
        member.role = role
        await self.db.commit()
        await self.db.refresh(member)
        return member

    async def remove_member(self, org_id: str, user_id: str) -> None:
        from app.models.organization import OrganizationMember
        from sqlalchemy import delete as sql_delete
        await self.db.execute(
            sql_delete(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        await self.db.commit()

    # ── Permission helpers ─────────────────────────────────────────────────

    async def get_member_role(self, org_id: str, user_id: str) -> str | None:
        from app.models.organization import OrganizationMember
        result = await self.db.execute(
            select(OrganizationMember.role).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def assert_member(self, org_id: str, user_id: str) -> None:
        role = await self.get_member_role(org_id, user_id)
        if not role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization.",
            )

    async def assert_admin(self, org_id: str, user_id: str) -> None:
        role = await self.get_member_role(org_id, user_id)
        if role not in ("admin", "owner"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin role required.",
            )

    async def assert_owner(self, org_id: str, user_id: str) -> None:
        role = await self.get_member_role(org_id, user_id)
        if role != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owner role required.",
            )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _generate_slug(self, name: str) -> str:
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug[:100]

    async def _unique_slug(self, base_slug: str) -> str:
        from app.models.organization import Organization
        slug = base_slug
        counter = 1
        while True:
            result = await self.db.execute(
                select(Organization.id).where(Organization.slug == slug)
            )
            if not result.scalar_one_or_none():
                return slug
            slug = f"{base_slug}-{counter}"
            counter += 1
