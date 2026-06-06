"""
Embedding Pipeline Module

Generates embeddings via DeepInfra's OpenAI-compatible endpoint.
Default model: BAAI/bge-large-en-v1.5  (1024 dimensions)

Features:
- Async batched embedding with configurable batch size
- Automatic rate-limit throttling between batches
- Query embedding for similarity search
- tiktoken-based token counting
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from langchain_openai import OpenAIEmbeddings

from app.ai.config import AIConfig

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """
    Wraps OpenAI Embeddings with async batching and rate-limit handling.

    Usage:
        pipeline = EmbeddingPipeline()
        vectors = await pipeline.embed_texts(["text a", "text b"])
        query_vector = await pipeline.embed_query("search query")
    """

    # Maximum texts per OpenAI embedding request
    BATCH_SIZE: int = 100

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        batch_size: int = BATCH_SIZE,
        inter_batch_delay: float = 0.1,
    ):
        self.model = model or AIConfig.RAG.embedding_model
        self.api_key = api_key or AIConfig.DEEPINFRA_API_KEY
        self.base_url = base_url or AIConfig.DEEPINFRA_BASE_URL
        self.batch_size = batch_size
        self.inter_batch_delay = inter_batch_delay

        # DeepInfra's BGE models:
        #   - do not support the `dimensions` reduction parameter
        #   - expect plain text strings (not tiktoken-encoded IDs), so we
        #     disable check_embedding_ctx_length and let DeepInfra truncate
        self._embedder = OpenAIEmbeddings(
            model=self.model,
            openai_api_key=self.api_key,
            openai_api_base=self.base_url,
            check_embedding_ctx_length=False,
        )

        # Lazy-load tiktoken to avoid import overhead at module level
        self._encoding = None

    # ── Token Counting ────────────────────────────────────────────────────────

    def _get_encoding(self):
        """Lazy-initialise tiktoken encoding."""
        if self._encoding is None:
            try:
                import tiktoken
                self._encoding = tiktoken.get_encoding("cl100k_base")
            except ImportError:
                logger.warning("tiktoken not installed; token counting will be approximate")
        return self._encoding

    def count_tokens(self, text: str) -> int:
        """Count the number of tokens in a text string."""
        encoding = self._get_encoding()
        if encoding is not None:
            return len(encoding.encode(text))
        # Fallback: rough approximation (1 token ≈ 4 characters)
        return max(1, len(text) // 4)

    def count_tokens_batch(self, texts: List[str]) -> List[int]:
        """Count tokens for a batch of texts."""
        return [self.count_tokens(t) for t in texts]

    # ── Embedding ─────────────────────────────────────────────────────────────

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.

        Processes in batches to respect API limits.
        Adds a small delay between batches to avoid rate limiting.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (one per input text).
        """
        if not texts:
            return []

        all_embeddings: List[List[float]] = []

        for batch_start in range(0, len(texts), self.batch_size):
            batch = texts[batch_start : batch_start + self.batch_size]

            logger.debug(
                "Embedding batch %d-%d of %d texts",
                batch_start + 1,
                batch_start + len(batch),
                len(texts),
            )

            batch_embeddings = await self._embedder.aembed_documents(batch)
            all_embeddings.extend(batch_embeddings)

            # Throttle between batches (not needed after the last one)
            if batch_start + self.batch_size < len(texts):
                await asyncio.sleep(self.inter_batch_delay)

        logger.info("Embedded %d texts using model=%s", len(texts), self.model)
        return all_embeddings

    async def embed_query(self, query: str) -> List[float]:
        """
        Generate an embedding for a single query string.

        Uses a separate OpenAI call optimised for queries
        (vs. document embeddings).

        Args:
            query: The search query text.

        Returns:
            Embedding vector as a list of floats.
        """
        return await self._embedder.aembed_query(query)

    async def embed_texts_with_counts(
        self, texts: List[str]
    ) -> tuple[List[List[float]], List[int]]:
        """
        Embed texts and return both vectors and token counts.

        Returns:
            Tuple of (embeddings, token_counts)
        """
        embeddings = await self.embed_texts(texts)
        token_counts = self.count_tokens_batch(texts)
        return embeddings, token_counts


# ── Module-level singleton (lazy — created on first access) ──────────────────

_embedding_pipeline: Optional[EmbeddingPipeline] = None


def get_embedding_pipeline() -> EmbeddingPipeline:
    """Return the shared EmbeddingPipeline instance, creating it on first call."""
    global _embedding_pipeline
    if _embedding_pipeline is None:
        _embedding_pipeline = EmbeddingPipeline()
    return _embedding_pipeline


# Backward-compat alias — access via get_embedding_pipeline() where possible
class _LazyPipeline:
    """Transparent proxy so `embedding_pipeline.embed_*` still works."""
    def __getattr__(self, name: str):
        return getattr(get_embedding_pipeline(), name)


embedding_pipeline = _LazyPipeline()
