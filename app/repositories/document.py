"""Document repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.core.constants import DocumentStatus
from app.models.document import Document
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    def __init__(self, db) -> None:
        super().__init__(db, Document)

    async def list_by_project(
        self,
        project_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[DocumentStatus] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Document], int]:
        from sqlalchemy import desc

        stmt = (
            select(Document)
            .where(Document.project_id == project_id)
            .where(Document.organization_id == org_id)
            .where(Document.deleted_at.is_(None))
        )
        if status:
            stmt = stmt.where(Document.status == status)
        if search:
            stmt = stmt.where(Document.original_filename.ilike(f"%{search}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(desc(Document.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def get_pending_documents(self, project_id: UUID) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.project_id == project_id)
            .where(Document.status == DocumentStatus.UPLOADED)
            .where(Document.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_processing(self, doc: Document) -> Document:
        doc.status = DocumentStatus.PROCESSING
        await self.db.flush()
        return doc

    async def mark_processed(
        self,
        doc: Document,
        page_count: Optional[int] = None,
        word_count: Optional[int] = None,
        raw_text: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> Document:
        doc.status = DocumentStatus.PROCESSED
        if page_count is not None:
            doc.page_count = page_count
        if word_count is not None:
            doc.word_count = word_count
        if raw_text is not None:
            doc.raw_text = raw_text
        if confidence is not None:
            doc.extraction_confidence = confidence
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def mark_failed(self, doc: Document, error: str) -> Document:
        doc.status = DocumentStatus.FAILED
        doc.processing_error = error
        await self.db.flush()
        return doc
