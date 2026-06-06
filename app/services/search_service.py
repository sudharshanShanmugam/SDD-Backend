"""
Search Service.
Semantic vector search + full-text BM25 hybrid search.
"""
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ENTITY_WEIGHTS = {
    "requirement": 1.0,
    "epic": 0.9,
    "story": 0.85,
    "task": 0.7,
    "document": 0.8,
}


class SearchService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(
        self,
        query: str,
        user_id: str,
        entity_types: list[str] | None = None,
        project_id: str | None = None,
        project_ids: list[str] | None = None,
        organization_id: str | None = None,
        use_semantic: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """
        Hybrid search: semantic vector search + full-text search with RRF fusion.
        Falls back to full-text only if embeddings are unavailable.
        """
        effective_types = entity_types or list(ENTITY_WEIGHTS.keys())

        if use_semantic:
            try:
                semantic_results = await self._semantic_search(
                    query=query,
                    entity_types=effective_types,
                    project_id=project_id,
                    project_ids=project_ids,
                    limit=page_size * 3,
                )
            except Exception as exc:
                logger.warning("Semantic search failed, falling back to full-text: %s", exc)
                semantic_results = []
        else:
            semantic_results = []

        fulltext_results = await self._fulltext_search(
            query=query,
            entity_types=effective_types,
            project_id=project_id,
            project_ids=project_ids,
            limit=page_size * 3,
        )

        # RRF fusion
        merged = self._reciprocal_rank_fusion(semantic_results, fulltext_results)
        total = len(merged)

        start = (page - 1) * page_size
        paginated = merged[start : start + page_size]

        return {
            "query": query,
            "results": paginated,
            "total": total,
            "page": page,
            "page_size": page_size,
            "search_type": "semantic+fulltext" if semantic_results else "fulltext",
        }

    async def _semantic_search(
        self,
        query: str,
        entity_types: list[str],
        project_id: str | None,
        project_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """Search using vector embeddings via pgvector."""
        from app.core.config import settings

        # Generate query embedding
        embedding = await self._embed_text(query)
        if not embedding:
            return []

        from sqlalchemy import text
        entity_filter = ", ".join(f"'{t}'" for t in entity_types)
        project_clause = ""
        if project_id:
            project_clause = f"AND project_id = '{project_id}'"
        elif project_ids:
            ids = ", ".join(f"'{p}'" for p in project_ids)
            project_clause = f"AND project_id IN ({ids})"

        sql = f"""
            SELECT
                entity_type,
                entity_id,
                title,
                snippet,
                1 - (embedding <=> :embedding::vector) AS score,
                metadata
            FROM search_index
            WHERE entity_type IN ({entity_filter})
            {project_clause}
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """

        try:
            result = await self.db.execute(
                text(sql),
                {"embedding": str(embedding), "limit": limit},
            )
            rows = result.mappings().all()
            return [
                {
                    "id": row["entity_id"],
                    "entity_type": row["entity_type"],
                    "title": row["title"],
                    "snippet": row["snippet"],
                    "score": float(row["score"]),
                    "metadata": row["metadata"] or {},
                    "url": self._build_url(row["entity_type"], row["entity_id"]),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("Semantic search query failed: %s", exc)
            return []

    async def _fulltext_search(
        self,
        query: str,
        entity_types: list[str],
        project_id: str | None,
        project_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """Full-text search using PostgreSQL tsvector."""
        from sqlalchemy import text

        entity_filter = ", ".join(f"'{t}'" for t in entity_types)
        project_clause = ""
        if project_id:
            project_clause = f"AND project_id = '{project_id}'"
        elif project_ids:
            ids = ", ".join(f"'{p}'" for p in project_ids)
            project_clause = f"AND project_id IN ({ids})"

        sql = f"""
            SELECT
                entity_type,
                entity_id,
                title,
                ts_headline('english', content, plainto_tsquery('english', :query)) AS snippet,
                ts_rank(search_vector, plainto_tsquery('english', :query)) AS score,
                metadata
            FROM search_index
            WHERE entity_type IN ({entity_filter})
            AND search_vector @@ plainto_tsquery('english', :query)
            {project_clause}
            ORDER BY score DESC
            LIMIT :limit
        """

        try:
            result = await self.db.execute(
                text(sql),
                {"query": query, "limit": limit},
            )
            rows = result.mappings().all()
            return [
                {
                    "id": row["entity_id"],
                    "entity_type": row["entity_type"],
                    "title": row["title"],
                    "snippet": row["snippet"],
                    "score": float(row["score"]),
                    "metadata": row["metadata"] or {},
                    "url": self._build_url(row["entity_type"], row["entity_id"]),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("Full-text search query failed: %s", exc)
            return []

    def _reciprocal_rank_fusion(
        self,
        list_a: list[dict],
        list_b: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """Merge two ranked result lists using Reciprocal Rank Fusion."""
        scores: dict[str, float] = {}
        entities: dict[str, dict] = {}

        for rank, item in enumerate(list_a, 1):
            key = f"{item['entity_type']}:{item['id']}"
            scores[key] = scores.get(key, 0) + 1 / (k + rank)
            entities[key] = item

        for rank, item in enumerate(list_b, 1):
            key = f"{item['entity_type']}:{item['id']}"
            scores[key] = scores.get(key, 0) + 1 / (k + rank)
            entities[key] = item

        sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)
        result = []
        for key in sorted_keys:
            item = dict(entities[key])
            item["score"] = round(scores[key], 6)
            result.append(item)
        return result

    async def get_suggestions(
        self,
        query: str,
        user_id: str,
        entity_types: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """Quick autocomplete from search_index title prefix match."""
        from sqlalchemy import text

        entity_filter = ""
        if entity_types:
            types = ", ".join(f"'{t}'" for t in entity_types)
            entity_filter = f"AND entity_type IN ({types})"

        sql = f"""
            SELECT entity_type, entity_id, title
            FROM search_index
            WHERE title ILIKE :prefix
            {entity_filter}
            ORDER BY title
            LIMIT :limit
        """
        try:
            result = await self.db.execute(
                text(sql),
                {"prefix": f"{query}%", "limit": limit},
            )
            return [
                {
                    "id": row[1],
                    "entity_type": row[0],
                    "title": row[2],
                    "url": self._build_url(row[0], row[1]),
                }
                for row in result.all()
            ]
        except Exception as exc:
            logger.error("Suggestions query failed: %s", exc)
            return []

    async def find_similar(
        self,
        entity_type: str,
        entity_id: str,
        user_id: str,
        limit: int,
    ) -> list[dict]:
        """Find semantically similar items using stored embeddings."""
        from sqlalchemy import text

        sql = """
            SELECT
                si.entity_type,
                si.entity_id,
                si.title,
                si.snippet,
                1 - (si.embedding <=> source.embedding) AS similarity
            FROM search_index si
            CROSS JOIN (
                SELECT embedding FROM search_index
                WHERE entity_type = :entity_type AND entity_id = :entity_id
                LIMIT 1
            ) source
            WHERE si.entity_id != :entity_id
            ORDER BY si.embedding <=> source.embedding
            LIMIT :limit
        """
        try:
            result = await self.db.execute(
                text(sql),
                {"entity_type": entity_type, "entity_id": entity_id, "limit": limit},
            )
            return [
                {
                    "id": row[1],
                    "entity_type": row[0],
                    "title": row[2],
                    "snippet": row[3],
                    "score": float(row[4]),
                    "url": self._build_url(row[0], row[1]),
                }
                for row in result.all()
            ]
        except Exception as exc:
            logger.error("Similar items query failed: %s", exc)
            return []

    async def _embed_text(self, text: str) -> list[float] | None:
        """Generate embedding for a text string."""
        try:
            from openai import AsyncOpenAI
            from app.core.config import settings

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=text[:8000],
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.warning("Embedding generation failed: %s", exc)
            return None

    def _build_url(self, entity_type: str, entity_id: str) -> str:
        url_map = {
            "requirement": f"/requirements/{entity_id}",
            "epic": f"/epics/{entity_id}",
            "story": f"/stories/{entity_id}",
            "task": f"/tasks/{entity_id}",
            "document": f"/documents/{entity_id}",
        }
        return url_map.get(entity_type, f"/{entity_type}s/{entity_id}")
