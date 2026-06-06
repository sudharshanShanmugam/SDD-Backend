"""
Contextual Retriever

Provides high-level RAG retrieval: embeds a query, searches the vector store,
and returns formatted context strings ready for LLM prompt injection.

This is the primary interface used by AI agents to fetch relevant context.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.ai.config import AIConfig
from app.ai.rag.embeddings import embedding_pipeline
from app.ai.rag.vectorstore import SimilarChunk, vector_store_manager

logger = logging.getLogger(__name__)


class ContextualRetriever:
    """
    High-level retrieval pipeline:
      1. Embed the query with EmbeddingPipeline
      2. Search ChromaDB for similar chunks via VectorStoreManager
      3. Format results for injection into LLM prompts

    Usage:
        retriever = ContextualRetriever()
        context = await retriever.retrieve_context(
            query="authentication requirements",
            organization_id=org_id,
            project_id=project_id,
        )
    """

    def __init__(
        self,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ):
        self.top_k = top_k or AIConfig.RAG.top_k
        self.score_threshold = score_threshold or AIConfig.RAG.similarity_threshold

    async def retrieve(
        self,
        query: str,
        organization_id: UUID | str,
        project_id: Optional[UUID | str] = None,
        document_id: Optional[UUID | str] = None,
        limit: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[SimilarChunk]:
        """
        Retrieve similar chunks for a query.

        Args:
            query: Natural language search query.
            organization_id: Owning organization (limits search to that collection).
            project_id: Optional project filter.
            document_id: Optional document filter.
            limit: Max results (defaults to configured top_k).
            score_threshold: Min similarity score (defaults to configured threshold).

        Returns:
            List of SimilarChunk sorted by descending similarity score.
        """
        query_embedding = await embedding_pipeline.embed_query(query)

        results = await vector_store_manager.similarity_search(
            organization_id=organization_id,
            query_embedding=query_embedding,
            project_id=project_id,
            document_id=document_id,
            limit=limit or self.top_k,
            score_threshold=score_threshold or self.score_threshold,
        )

        logger.debug(
            "retrieve: query=%r, org=%s, results=%d",
            query[:80],
            organization_id,
            len(results),
        )

        return results

    async def retrieve_context(
        self,
        query: str,
        organization_id: UUID | str,
        project_id: Optional[UUID | str] = None,
        document_id: Optional[UUID | str] = None,
        limit: Optional[int] = None,
        score_threshold: Optional[float] = None,
        max_context_tokens: Optional[int] = None,
    ) -> str:
        """
        Retrieve similar chunks and format them as a context string for LLM injection.

        The returned string is ready to be inserted into a prompt template as
        {rag_context}.

        Args:
            query: Natural language search query.
            organization_id: Owning organization.
            project_id: Optional project filter.
            document_id: Optional document filter.
            limit: Max chunks to retrieve.
            score_threshold: Min similarity score.
            max_context_tokens: Truncate context if it exceeds this token count.

        Returns:
            Formatted context string, or empty string if no results found.
        """
        chunks = await self.retrieve(
            query=query,
            organization_id=organization_id,
            project_id=project_id,
            document_id=document_id,
            limit=limit,
            score_threshold=score_threshold,
        )

        if not chunks:
            return ""

        return self._format_context(
            chunks=chunks,
            max_tokens=max_context_tokens or AIConfig.RAG.max_context_tokens,
        )

    async def retrieve_as_dicts(
        self,
        query: str,
        organization_id: UUID | str,
        project_id: Optional[UUID | str] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve chunks and return them as plain dicts.

        Compatible with the `rag_results` parameter expected by BaseAgent.run().
        """
        chunks = await self.retrieve(
            query=query,
            organization_id=organization_id,
            project_id=project_id,
            **kwargs,
        )
        return [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "project_id": c.project_id,
                "content": c.content,
                "score": c.score,
                **c.metadata,
            }
            for c in chunks
        ]

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _format_context(
        self,
        chunks: List[SimilarChunk],
        max_tokens: int = 8000,
    ) -> str:
        """
        Format retrieved chunks into a numbered reference block.

        Truncates to max_tokens (approximate, based on character count).
        """
        parts = []
        char_budget = max_tokens * 4  # rough chars-per-token estimate
        used = 0

        for i, chunk in enumerate(chunks, 1):
            section = f" ({chunk.metadata.get('section_title')})" if chunk.metadata.get("section_title") else ""
            header = f"[Reference {i}]{section} (similarity: {chunk.score:.2f})"
            block = f"{header}\n{chunk.content}"

            if used + len(block) > char_budget:
                remaining = char_budget - used
                if remaining > 200:
                    block = block[:remaining] + "\n[truncated]"
                    parts.append(block)
                break

            parts.append(block)
            used += len(block)

        if not parts:
            return ""

        return "## Relevant Context from Knowledge Base\n\n" + "\n\n---\n\n".join(parts)


# ── Module-level singleton ────────────────────────────────────────────────────

contextual_retriever = ContextualRetriever()
