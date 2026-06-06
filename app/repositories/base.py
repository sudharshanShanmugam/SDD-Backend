"""Generic base repository with full CRUD, soft-delete, and multi-tenant support."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Generic, Optional, Sequence, Type, TypeVar
from uuid import UUID

from sqlalchemy import asc, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseRepository(Generic[ModelT]):
    """
    Generic async repository providing:
    - create / get_by_id / get_by_ids / list / update / soft_delete / hard_delete
    - Multi-tenant filtering via organization_id
    - Pagination, sorting, and search helpers
    """

    def __init__(self, db: AsyncSession, model: Type[ModelT]) -> None:
        self.db = db
        self.model = model

    # ── CREATE ────────────────────────────────────────────────────────────────

    async def create(self, **kwargs: Any) -> ModelT:
        """Create a new instance and flush to the DB (not yet committed)."""
        obj = self.model(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def bulk_create(self, items: list[dict[str, Any]]) -> list[ModelT]:
        """Create multiple instances in a single flush."""
        objs = [self.model(**item) for item in items]
        self.db.add_all(objs)
        await self.db.flush()
        return objs

    # ── READ ──────────────────────────────────────────────────────────────────

    async def get_by_id(
        self,
        id: UUID,
        org_id: Optional[UUID] = None,
        include_deleted: bool = False,
    ) -> Optional[ModelT]:
        """Fetch a single record by primary key."""
        stmt = select(self.model).where(self.model.id == id)
        if org_id and hasattr(self.model, "organization_id"):
            stmt = stmt.where(self.model.organization_id == org_id)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_by_ids(
        self,
        ids: list[UUID],
        org_id: Optional[UUID] = None,
        include_deleted: bool = False,
    ) -> list[ModelT]:
        """Fetch multiple records by primary key list."""
        if not ids:
            return []
        stmt = select(self.model).where(self.model.id.in_(ids))
        if org_id and hasattr(self.model, "organization_id"):
            stmt = stmt.where(self.model.organization_id == org_id)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_one_by(self, org_id: Optional[UUID] = None, **filters: Any) -> Optional[ModelT]:
        """Fetch the first record matching all keyword filters."""
        stmt = select(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        if org_id and hasattr(self.model, "organization_id"):
            stmt = stmt.where(self.model.organization_id == org_id)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list(
        self,
        org_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        include_deleted: bool = False,
        filters: Optional[dict[str, Any]] = None,
    ) -> tuple[list[ModelT], int]:
        """
        Return a paginated (items, total_count) tuple.
        filters dict keys must be exact column names.
        """
        base_stmt = select(self.model)

        if org_id and hasattr(self.model, "organization_id"):
            base_stmt = base_stmt.where(self.model.organization_id == org_id)

        if not include_deleted and hasattr(self.model, "deleted_at"):
            base_stmt = base_stmt.where(self.model.deleted_at.is_(None))

        if filters:
            for field, value in filters.items():
                if value is not None and hasattr(self.model, field):
                    base_stmt = base_stmt.where(getattr(self.model, field) == value)

        # Count query
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar_one()

        # Sorting
        sort_col = getattr(self.model, sort_by, None)
        if sort_col is not None:
            base_stmt = base_stmt.order_by(
                desc(sort_col) if sort_order == "desc" else asc(sort_col)
            )

        # Pagination
        offset = (page - 1) * page_size
        base_stmt = base_stmt.offset(offset).limit(page_size)

        result = await self.db.execute(base_stmt)
        items = list(result.scalars().all())
        return items, total

    async def count(
        self,
        org_id: Optional[UUID] = None,
        include_deleted: bool = False,
        **filters: Any,
    ) -> int:
        """Count records matching the given filters."""
        stmt = select(func.count()).select_from(self.model)
        if org_id and hasattr(self.model, "organization_id"):
            stmt = stmt.where(self.model.organization_id == org_id)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        for field, value in filters.items():
            if value is not None and hasattr(self.model, field):
                stmt = stmt.where(getattr(self.model, field) == value)
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def exists(self, id: UUID, org_id: Optional[UUID] = None) -> bool:
        """Return True if a non-deleted record with this ID exists."""
        stmt = select(func.count()).select_from(self.model).where(self.model.id == id)
        if org_id and hasattr(self.model, "organization_id"):
            stmt = stmt.where(self.model.organization_id == org_id)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalar_one() > 0

    # ── UPDATE ────────────────────────────────────────────────────────────────

    async def update(
        self,
        obj: ModelT,
        updated_by: Optional[UUID] = None,
        **kwargs: Any,
    ) -> ModelT:
        """Apply keyword updates to an ORM instance and flush."""
        for key, value in kwargs.items():
            if hasattr(obj, key) and value is not None:
                setattr(obj, key, value)
        if updated_by and hasattr(obj, "updated_by"):
            obj.updated_by = updated_by
        obj.updated_at = datetime.now(tz=timezone.utc)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update_by_id(
        self,
        id: UUID,
        org_id: Optional[UUID] = None,
        updated_by: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Optional[ModelT]:
        """Fetch by id and apply updates; returns updated object or None."""
        obj = await self.get_by_id(id, org_id=org_id)
        if obj is None:
            return None
        return await self.update(obj, updated_by=updated_by, **kwargs)

    # ── DELETE ────────────────────────────────────────────────────────────────

    async def soft_delete(
        self, obj: ModelT, deleted_by: Optional[UUID] = None
    ) -> ModelT:
        """Set deleted_at timestamp (soft delete)."""
        if hasattr(obj, "deleted_at"):
            obj.deleted_at = datetime.now(tz=timezone.utc)
        if deleted_by and hasattr(obj, "updated_by"):
            obj.updated_by = deleted_by
        await self.db.flush()
        return obj

    async def restore(self, obj: ModelT) -> ModelT:
        """Clear deleted_at to restore a soft-deleted record."""
        if hasattr(obj, "deleted_at"):
            obj.deleted_at = None
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def hard_delete(self, obj: ModelT) -> None:
        """Permanently delete a record from the database."""
        await self.db.delete(obj)
        await self.db.flush()

    # ── HELPER ────────────────────────────────────────────────────────────────

    def _apply_search(self, stmt: Any, search: str, columns: list[str]) -> Any:
        """Apply ILIKE search across multiple string columns."""
        from sqlalchemy import or_

        pattern = f"%{search.strip()}%"
        conditions = [
            getattr(self.model, col).ilike(pattern)
            for col in columns
            if hasattr(self.model, col)
        ]
        if conditions:
            stmt = stmt.where(or_(*conditions))
        return stmt
