"""
Project Service.
Project lifecycle management, workflow stage transitions.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _serialize_member(member, user) -> dict:
    return {
        "id": str(member.id),
        "userId": str(user.id),
        "projectId": str(member.project_id),
        "role": str(member.role),
        "joinedAt": str(member.created_at) if hasattr(member, "created_at") and member.created_at else None,
        "user": {
            "id": str(user.id),
            "displayName": user.full_name,
            "email": user.email,
            "avatar": getattr(user, "avatar_url", None),
            "jobTitle": None,
            "status": "active" if user.is_active else "inactive",
        },
    }


WORKFLOW_TRANSITIONS = {
    "discovery": ["requirements", "archived"],
    "requirements": ["design", "discovery", "archived"],
    "design": ["development", "requirements", "archived"],
    "development": ["qa", "design", "archived"],
    "qa": ["staging", "development", "archived"],
    "staging": ["production", "qa", "archived"],
    "production": ["archived"],
    "archived": [],
}


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_project(
        self,
        name: str,
        workspace_id: str,
        description: str | None,
        key: str | None,
        workflow_stage: str,
        start_date: str | None,
        target_date: str | None,
        settings: dict,
        created_by: str,
    ):
        from app.models.project import Project, ProjectMember
        from app.models.workspace import Workspace
        from sqlalchemy import select as sa_select

        # Resolve organization_id from the workspace (required NOT NULL column)
        ws_row = await self.db.execute(
            sa_select(Workspace.organization_id).where(
                Workspace.id == uuid.UUID(workspace_id)
            )
        )
        organization_id = ws_row.scalar_one_or_none()
        if organization_id is None:
            raise HTTPException(status_code=404, detail="Workspace not found.")

        project_key = key or await self._generate_key(name, workspace_id)

        now = datetime.now(tz=timezone.utc)
        project = Project(
            id=uuid.uuid4(),
            name=name,
            key=project_key,
            organization_id=organization_id,
            workspace_id=uuid.UUID(workspace_id),
            description=description,
            workflow_stage=workflow_stage,
            start_date=start_date,
            target_date=target_date,
            settings=settings or {},
            created_by=uuid.UUID(created_by) if isinstance(created_by, str) else created_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(project)

        member = ProjectMember(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=uuid.UUID(created_by) if isinstance(created_by, str) else created_by,
            role="owner",
        )
        self.db.add(member)

        try:
            await self.db.flush()   # sends INSERTs, raises IntegrityError on duplicate key
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            # Detect unique-key violation on (organization_id, key)
            from sqlalchemy.exc import IntegrityError
            if isinstance(exc, IntegrityError) and "uq_project_org_key" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A project with key '{project_key}' already exists in this organization.",
                )
            raise
        await self.db.refresh(project)
        return project

    async def get_by_id(self, project_id: str):
        from app.models.project import Project
        result = await self.db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def list_projects(
        self,
        user_id: str,
        workspace_id: str | None,
        workflow_stage: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from app.models.project import Project, ProjectMember

        query = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        if workspace_id:
            query = query.where(Project.workspace_id == workspace_id)
        if workflow_stage:
            query = query.where(Project.workflow_stage == workflow_stage)
        if search:
            query = query.where(Project.name.ilike(f"%{search}%"))

        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        query = query.order_by(Project.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
        items = (await self.db.execute(query)).scalars().all()

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def update_project(self, project_id: str, data: dict):
        from app.models.project import Project
        data["updated_at"] = datetime.now(tz=timezone.utc)
        await self.db.execute(update(Project).where(Project.id == project_id).values(**data))
        await self.db.commit()
        return await self.get_by_id(project_id)

    async def delete_project(self, project_id: str) -> None:
        from app.models.project import Project
        from sqlalchemy import delete as sql_delete
        await self.db.execute(sql_delete(Project).where(Project.id == project_id))
        await self.db.commit()

    async def transition_stage(
        self,
        project_id: str,
        new_stage: str,
        changed_by: str,
        reason: str | None,
    ):
        project = await self.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

        allowed = WORKFLOW_TRANSITIONS.get(project.workflow_stage, [])
        if new_stage not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot transition from '{project.workflow_stage}' to '{new_stage}'. "
                       f"Allowed: {allowed}",
            )

        from app.services.audit_service import AuditService
        audit_svc = AuditService(self.db)
        await audit_svc.log(
            entity_type="project",
            entity_id=project_id,
            action="workflow_stage_changed",
            actor_id=changed_by,
            metadata={
                "from_stage": project.workflow_stage,
                "to_stage": new_stage,
                "reason": reason,
            },
        )

        return await self.update_project(project_id, {"workflow_stage": new_stage})

    async def list_members(self, project_id: str) -> list:
        from app.models.project import ProjectMember
        from app.models.user import User
        result = await self.db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
        )
        return [_serialize_member(m, u) for m, u in result.all()]

    async def add_member(self, project_id: str, user_id: str, role: str):
        from app.models.project import ProjectMember
        from app.models.user import User
        from sqlalchemy import select as sa_select
        try:
            proj_uuid = uuid.UUID(project_id) if isinstance(project_id, str) else project_id
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        except (ValueError, TypeError):
            return None
        member = ProjectMember(
            id=uuid.uuid4(),
            project_id=proj_uuid,
            user_id=user_uuid,
            role=role,
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(member)
        user_result = await self.db.execute(sa_select(User).where(User.id == user_uuid))
        user = user_result.scalar_one_or_none()
        return _serialize_member(member, user) if user else {"userId": str(user_uuid), "role": role}

    async def update_member_role(self, project_id: str, user_id: str, role: str):
        from app.models.project import ProjectMember
        from app.models.user import User
        from sqlalchemy import select as sa_select, update as sa_update
        await self.db.execute(
            sa_update(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
            .values(role=role)
        )
        await self.db.commit()
        result = await self.db.execute(
            sa_select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        )
        row = result.first()
        return _serialize_member(row[0], row[1]) if row else None

    async def remove_member(self, project_id: str, user_id: str) -> bool:
        from app.models.project import ProjectMember
        from sqlalchemy import delete as sa_delete
        result = await self.db.execute(
            sa_delete(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def get_stats(self, project_id: str) -> dict:
        """Aggregate project statistics."""
        # Placeholder - would query epics/stories/tasks tables
        return {
            "project_id": project_id,
            "epic_count": 0,
            "story_count": 0,
            "task_count": 0,
            "completed_stories": 0,
            "in_progress_stories": 0,
            "todo_stories": 0,
        }

    async def get_member_role(self, project_id: str, user_id: str) -> str | None:
        from app.models.project import ProjectMember
        result = await self.db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _is_org_admin(self, user_id: str) -> bool:
        """Return True if user is SUPER_ADMIN or ORG_ADMIN (bypasses project membership checks)."""
        from app.models.user import User
        result = await self.db.execute(select(User.role).where(User.id == user_id))
        role = result.scalar_one_or_none()
        return role in ("super_admin", "org_admin")

    async def assert_access(self, project_id: str, user_id: str) -> None:
        if await self._is_org_admin(user_id):
            return
        role = await self.get_member_role(project_id, user_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    async def assert_manager(self, project_id: str, user_id: str) -> None:
        if await self._is_org_admin(user_id):
            return
        role = await self.get_member_role(project_id, user_id)
        if role not in ("manager", "owner"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager role required.")

    async def assert_owner(self, project_id: str, user_id: str) -> None:
        if await self._is_org_admin(user_id):
            return
        role = await self.get_member_role(project_id, user_id)
        if role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required.")

    async def _generate_key(self, name: str, workspace_id: str) -> str:
        import re
        words = re.sub(r"[^A-Za-z\s]", "", name).split()
        if len(words) >= 2:
            key = "".join(w[0].upper() for w in words[:4])
        else:
            key = name[:4].upper()
        # Ensure minimum length
        key = key.ljust(2, "X")[:10]
        return key
