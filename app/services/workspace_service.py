"""
Workspace Service.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class WorkspaceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _slugify(name: str) -> str:
        """Convert a name to a URL-safe slug."""
        import re
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"[\s-]+", "-", slug)
        return slug[:100] or "workspace"

    async def create_workspace(
        self,
        name: str,
        org_id: str,
        description: str | None,
        color: str | None,
        icon: str | None,
        settings: dict,
        created_by: str,
    ):
        from app.models.workspace import Workspace, WorkspaceMember
        from sqlalchemy import select as sa_select
        import re

        now = datetime.now(tz=timezone.utc)
        base_slug = self._slugify(name)

        # Ensure slug is unique within the org
        slug = base_slug
        suffix = 1
        while True:
            existing = await self.db.execute(
                sa_select(Workspace).where(
                    Workspace.organization_id == org_id,
                    Workspace.slug == slug,
                )
            )
            if not existing.scalar_one_or_none():
                break
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        ws = Workspace(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            organization_id=org_id,
            description=description,
            color=color,
            icon=icon,
            settings=settings or {},
            is_active=True,
            is_default=False,
            created_by=uuid.UUID(created_by) if isinstance(created_by, str) else created_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(ws)
        await self.db.flush()

        member = WorkspaceMember(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            user_id=uuid.UUID(created_by) if isinstance(created_by, str) else created_by,
            role="owner",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.db.add(member)

        await self.db.commit()
        await self.db.refresh(ws)
        return ws

    async def get_by_id(self, workspace_id: str):
        from app.models.workspace import Workspace
        result = await self.db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def list_workspaces(
        self,
        user_id: str,
        org_id: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.workspace import Workspace, WorkspaceMember
        from sqlalchemy import func

        query = (
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
        )
        if org_id:
            query = query.where(Workspace.organization_id == org_id)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        query = query.order_by(Workspace.name).offset((page - 1) * page_size).limit(page_size)
        items = (await self.db.execute(query)).scalars().all()
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def update_workspace(self, workspace_id: str, data: dict):
        from app.models.workspace import Workspace
        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(
            update(Workspace).where(Workspace.id == workspace_id).values(**data)
        )
        await self.db.commit()
        return await self.get_by_id(workspace_id)

    async def delete_workspace(self, workspace_id: str) -> None:
        from app.models.workspace import Workspace
        from sqlalchemy import delete as sql_delete
        await self.db.execute(sql_delete(Workspace).where(Workspace.id == workspace_id))
        await self.db.commit()

    async def list_members(self, workspace_id: str) -> list:
        from app.models.workspace import WorkspaceMember
        from app.models.user import User
        result = await self.db.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )
        return [
            {
                "user_id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "role": m.role,
            }
            for m, u in result.all()
        ]

    async def add_member(self, workspace_id: str, user_id: str, role: str):
        from app.models.workspace import WorkspaceMember
        try:
            ws_uuid = uuid.UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            return None
        member = WorkspaceMember(
            id=uuid.uuid4(),
            workspace_id=ws_uuid,
            user_id=user_uuid,
            role=role,
        )
        self.db.add(member)
        await self.db.commit()
        return {"workspace_id": str(ws_uuid), "user_id": str(user_uuid), "role": role}

    async def remove_member(self, workspace_id: str, user_id: str) -> None:
        from app.models.workspace import WorkspaceMember
        from sqlalchemy import delete as _delete
        try:
            ws_uuid = uuid.UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            return
        await self.db.execute(
            _delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_uuid,
                WorkspaceMember.user_id == user_uuid,
            )
        )
        await self.db.commit()

    async def get_member_role(self, workspace_id: str, user_id: str) -> str | None:
        from app.models.workspace import WorkspaceMember
        result = await self.db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def assert_access(self, workspace_id: str, user_id: str) -> None:
        role = await self.get_member_role(workspace_id, user_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    async def assert_admin(self, workspace_id: str, user_id: str) -> None:
        role = await self.get_member_role(workspace_id, user_id)
        if role not in ("admin", "owner", "org_admin", "super_admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required.")
