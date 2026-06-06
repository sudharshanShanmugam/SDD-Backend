"""
Document Indexer

End-to-end pipeline for ingesting a document into the RAG system:
  1. Chunk the document with SmartDocumentChunker
  2. Generate embeddings with EmbeddingPipeline
  3. Upsert vectors via VectorStoreManager (ChromaDB)

This is the high-level API used by document upload handlers and
the document processing workflow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.ai.rag.chunker import SmartDocumentChunker, document_chunker
from app.ai.rag.embeddings import embedding_pipeline
from app.ai.rag.vectorstore import vector_store_manager

logger = logging.getLogger(__name__)


@dataclass
class IndexingResult:
    """Summary of a document indexing operation."""
    document_id: str
    organization_id: str
    project_id: str
    chunks_created: int
    vectors_stored: int
    total_tokens: int
    success: bool
    error: Optional[str] = None


class DocumentIndexer:
    """
    Orchestrates the full RAG ingestion pipeline for a single document.

    Usage:
        indexer = DocumentIndexer()
        result = await indexer.index_document(
            document_id=doc_id,
            content=raw_text,
            organization_id=org_id,
            project_id=project_id,
        )
    """

    def __init__(
        self,
        chunker: Optional[SmartDocumentChunker] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        self.chunker = chunker or SmartDocumentChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def index_document(
        self,
        document_id: str | UUID,
        content: str,
        organization_id: str | UUID,
        project_id: str | UUID,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IndexingResult:
        """
        Chunk, embed, and index a document into the vector store.

        Args:
            document_id: Unique document identifier.
            content: Raw document text to index.
            organization_id: Owning organization (determines ChromaDB collection).
            project_id: Project this document belongs to.
            metadata: Additional metadata to store alongside each chunk.

        Returns:
            IndexingResult with operation summary.
        """
        doc_id_str = str(document_id)
        org_id_str = str(organization_id)
        project_id_str = str(project_id)

        try:
            # 1. Chunk the document
            chunk_metadata = {
                "document_id": doc_id_str,
                "project_id": project_id_str,
                "organization_id": org_id_str,
                **(metadata or {}),
            }

            chunks = self.chunker.chunk_text(text=content, metadata=chunk_metadata)

            if not chunks:
                logger.warning(
                    "index_document: no chunks produced for document %s", doc_id_str
                )
                return IndexingResult(
                    document_id=doc_id_str,
                    organization_id=org_id_str,
                    project_id=project_id_str,
                    chunks_created=0,
                    vectors_stored=0,
                    total_tokens=0,
                    success=True,
                )

            # 2. Generate embeddings
            texts = [c.text for c in chunks]
            embeddings, token_counts = await embedding_pipeline.embed_texts_with_counts(texts)

            total_tokens = sum(token_counts)

            # 3. Attach embeddings and IDs to chunk proxies for upsert
            import uuid as _uuid

            class _IndexChunk:
                def __init__(self, chunk, embedding, idx):
                    self.id = _uuid.uuid4()
                    self.embedding = embedding
                    self.content = chunk.text
                    self.chunk_index = chunk.chunk_index
                    self.section_title = chunk.section_title
                    self.document_id = doc_id_str
                    self.project_id = project_id_str
                    self.token_count = token_counts[idx]

            index_chunks = [
                _IndexChunk(chunk, emb, i)
                for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
            ]

            # 4. Upsert into ChromaDB
            await vector_store_manager.upsert_chunks(
                organization_id=organization_id,
                chunks=index_chunks,
            )

            logger.info(
                "Indexed document %s: %d chunks, %d tokens (org=%s)",
                doc_id_str,
                len(chunks),
                total_tokens,
                org_id_str,
            )

            return IndexingResult(
                document_id=doc_id_str,
                organization_id=org_id_str,
                project_id=project_id_str,
                chunks_created=len(chunks),
                vectors_stored=len(chunks),
                total_tokens=total_tokens,
                success=True,
            )

        except Exception as exc:
            logger.exception(
                "index_document failed for document %s: %s", doc_id_str, exc
            )
            return IndexingResult(
                document_id=doc_id_str,
                organization_id=org_id_str,
                project_id=project_id_str,
                chunks_created=0,
                vectors_stored=0,
                total_tokens=0,
                success=False,
                error=str(exc),
            )

    async def delete_document(
        self,
        document_id: str | UUID,
        organization_id: str | UUID,
    ) -> None:
        """
        Remove all indexed vectors for a document.

        Args:
            document_id: Document to remove from the vector store.
            organization_id: Owning organization.
        """
        await vector_store_manager.delete_document_vectors(
            organization_id=organization_id,
            document_id=document_id,
        )
        logger.info(
            "Deleted index for document %s (org=%s)", document_id, organization_id
        )

    async def reindex_document(
        self,
        document_id: str | UUID,
        content: str,
        organization_id: str | UUID,
        project_id: str | UUID,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IndexingResult:
        """
        Delete existing vectors for a document and re-index fresh content.

        Useful when a document is updated.
        """
        # Delete old vectors first
        try:
            await self.delete_document(
                document_id=document_id,
                organization_id=organization_id,
            )
        except Exception as exc:
            logger.warning(
                "Could not delete old vectors for document %s: %s",
                document_id,
                exc,
            )

        # Re-index
        return await self.index_document(
            document_id=document_id,
            content=content,
            organization_id=organization_id,
            project_id=project_id,
            metadata=metadata,
        )


# ── Module-level singleton ────────────────────────────────────────────────────

document_indexer = DocumentIndexer()
