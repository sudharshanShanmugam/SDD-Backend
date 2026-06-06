"""
ChromaDB Vector Store Integration

Replaces Qdrant with ChromaDB (embedded, no separate server required).
Data is persisted to ./chroma_db by default (configurable via CHROMA_PERSIST_DIR).

Collections are namespaced per-organization:
    sdd_org_<org_id_underscores>
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import chromadb
from chromadb.config import Settings
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Persist directory — override with env var CHROMA_PERSIST_DIR
CHROMA_PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db")
VECTOR_SIZE = int(os.environ.get("CHROMA_VECTOR_SIZE", "1024"))
COLLECTION_PREFIX = "sdd_org_"


# ── Result Model ──────────────────────────────────────────────────────────────

class SimilarChunk(BaseModel):
    chunk_id: str
    document_id: str
    project_id: str
    organization_id: str
    content: str
    score: float
    metadata: Dict[str, Any] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _org_collection_name(organization_id: UUID | str) -> str:
    return f"{COLLECTION_PREFIX}{str(organization_id).replace('-', '_')}"


def _build_where(project_id=None, document_id=None) -> Optional[dict]:
    conditions = []
    if project_id:
        conditions.append({"project_id": {"$eq": str(project_id)}})
    if document_id:
        conditions.append({"document_id": {"$eq": str(document_id)}})
    if not conditions:
        return None
    return {"$and": conditions} if len(conditions) > 1 else conditions[0]


# ── Vector Store Manager ──────────────────────────────────────────────────────

class VectorStoreManager:
    """
    ChromaDB-backed vector store for the SDD platform.
    Identical public API to the former Qdrant VectorStoreManager.
    """

    def __init__(self, persist_dir: str = CHROMA_PERSIST_DIR):
        self._persist_dir = persist_dir
        self._client: Optional[chromadb.ClientAPI] = None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_client(self) -> chromadb.ClientAPI:
        if self._client is None:
            os.makedirs(self._persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self._persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("ChromaDB client initialised (persist_dir=%s)", self._persist_dir)
        return self._client

    def _get_or_create_collection(self, org_id: UUID | str) -> chromadb.Collection:
        name = _org_collection_name(org_id)
        return self._get_client().get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Health-check / warm-up. Called at application startup."""
        try:
            await asyncio.to_thread(self._get_client)
            logger.info("VectorStoreManager ready (ChromaDB, persist_dir=%s)", self._persist_dir)
        except Exception as exc:
            logger.warning("VectorStoreManager init warning: %s", exc)

    def get_collection_name(self, organization_id: UUID | str) -> str:
        return _org_collection_name(organization_id)

    async def ensure_collection(self, organization_id: UUID | str) -> str:
        await asyncio.to_thread(self._get_or_create_collection, organization_id)
        return _org_collection_name(organization_id)

    # ── Write Operations ──────────────────────────────────────────────────────

    async def upsert_chunks(self, organization_id: UUID | str, chunks: list) -> None:
        """Upsert chunk objects (must have .id, .embedding, .content, etc.)."""
        if not chunks:
            return

        ids = [str(c.id) for c in chunks]
        embeddings = [c.embedding for c in chunks]
        documents = [getattr(c, "content", "") for c in chunks]
        metadatas = [
            {
                "document_id": str(getattr(c, "document_id", "")),
                "project_id": str(getattr(c, "project_id", "")),
                "organization_id": str(organization_id),
                "chunk_index": getattr(c, "chunk_index", 0),
                "section_title": getattr(c, "section_title", "") or "",
                "token_count": getattr(c, "token_count", 0),
            }
            for c in chunks
        ]

        def _upsert():
            col = self._get_or_create_collection(organization_id)
            col.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

        await asyncio.to_thread(_upsert)
        logger.info("Upserted %d vectors for org=%s", len(chunks), organization_id)

    async def upsert_documents(
        self,
        collection_name: str,
        documents: list,
        embeddings: List[List[float]],
    ) -> None:
        """LangChain Document-compatible upsert (used by document_workflow.py)."""
        if not documents or len(documents) != len(embeddings):
            raise ValueError(f"documents ({len(documents)}) and embeddings ({len(embeddings)}) must match")

        import uuid as _uuid

        ids, docs, metas = [], [], []
        for doc, vec in zip(documents, embeddings):
            content = getattr(doc, "page_content", None) or getattr(doc, "text", "")
            metadata = dict(getattr(doc, "metadata", {}) or {})
            # Chroma metadatas must contain only str/int/float/bool
            clean_meta = {k: str(v) if not isinstance(v, (str, int, float, bool)) else v
                          for k, v in metadata.items()}
            ids.append(str(_uuid.uuid4()))
            docs.append(content)
            metas.append(clean_meta)

        def _upsert():
            client = self._get_client()
            col = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            col.upsert(ids=ids, embeddings=embeddings, documents=docs, metadatas=metas)

        await asyncio.to_thread(_upsert)
        logger.info("upsert_documents: %d vectors into %s", len(ids), collection_name)

    # ── Read Operations ───────────────────────────────────────────────────────

    async def similarity_search(
        self,
        organization_id: UUID | str,
        query_embedding: List[float],
        project_id: Optional[UUID | str] = None,
        document_id: Optional[UUID | str] = None,
        limit: int = 10,
        score_threshold: float = 0.70,
    ) -> List[SimilarChunk]:
        where = _build_where(project_id, document_id)

        def _search():
            col = self._get_or_create_collection(organization_id)
            kwargs: dict = {"query_embeddings": [query_embedding], "n_results": limit, "include": ["documents", "metadatas", "distances"]}
            if where:
                kwargs["where"] = where
            return col.query(**kwargs)

        try:
            results = await asyncio.to_thread(_search)
        except Exception as exc:
            logger.error("ChromaDB similarity_search error: %s", exc)
            return []

        similar_chunks: List[SimilarChunk] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for chunk_id, content, meta, dist in zip(ids, docs, metas, distances):
            # ChromaDB returns L2 distance for cosine space; convert to similarity
            score = 1.0 - dist
            if score < score_threshold:
                continue
            similar_chunks.append(SimilarChunk(
                chunk_id=chunk_id,
                document_id=meta.get("document_id", ""),
                project_id=meta.get("project_id", ""),
                organization_id=meta.get("organization_id", str(organization_id)),
                content=content or "",
                score=score,
                metadata={k: v for k, v in meta.items() if k not in ("document_id", "project_id", "organization_id", "content")},
            ))

        logger.debug("similarity_search: %d results (threshold=%.2f)", len(similar_chunks), score_threshold)
        return similar_chunks

    # ── Delete Operations ─────────────────────────────────────────────────────

    async def delete_document_vectors(self, organization_id: UUID | str, document_id: UUID | str) -> None:
        def _delete():
            col = self._get_or_create_collection(organization_id)
            col.delete(where={"document_id": {"$eq": str(document_id)}})

        await asyncio.to_thread(_delete)
        logger.info("Deleted vectors for document=%s org=%s", document_id, organization_id)

    async def delete_project_vectors(self, organization_id: UUID | str, project_id: UUID | str) -> None:
        def _delete():
            col = self._get_or_create_collection(organization_id)
            col.delete(where={"project_id": {"$eq": str(project_id)}})

        await asyncio.to_thread(_delete)
        logger.info("Deleted vectors for project=%s org=%s", project_id, organization_id)

    async def get_collection_info(self, organization_id: UUID | str) -> Dict[str, Any]:
        collection_name = _org_collection_name(organization_id)
        try:
            def _info():
                col = self._get_or_create_collection(organization_id)
                return col.count()
            count = await asyncio.to_thread(_info)
            return {"collection_name": collection_name, "vectors_count": count, "status": "green"}
        except Exception as exc:
            return {"collection_name": collection_name, "error": str(exc)}


# ── Module-level singleton ────────────────────────────────────────────────────

vector_store_manager = VectorStoreManager()
