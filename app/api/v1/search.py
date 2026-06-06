"""
Global semantic search API routes.
"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    entity_types: list[str] | None = None
    project_ids: list[str] | None = None
    organization_id: str | None = None
    use_semantic: bool = True
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class SearchResultItem(BaseModel):
    id: str
    entity_type: str
    title: str
    snippet: str
    score: float
    metadata: dict
    url: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    total: int
    page: int
    page_size: int
    search_type: str


@router.get(
    "",
    summary="Global search across all entities",
)
async def global_search(
    q: str = Query(min_length=1, max_length=1000, description="Search query"),
    entity_types: str | None = Query(default=None, description="Comma-separated entity types"),
    project_id: str | None = Query(default=None),
    semantic: bool = Query(default=True, description="Use semantic vector search"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Search across requirements, epics, stories, tasks, and documents.
    Combines semantic vector search with full-text BM25 search.
    """
    svc = SearchService(db)
    type_list = [t.strip() for t in entity_types.split(",")] if entity_types else None

    return await svc.search(
        query=q,
        user_id=str(current_user.id),
        entity_types=type_list,
        project_id=project_id,
        use_semantic=semantic,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/advanced",
    summary="Advanced search with full configuration",
)
async def advanced_search(
    payload: SearchRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Advanced search with full filtering control."""
    svc = SearchService(db)
    return await svc.search(
        query=payload.query,
        user_id=str(current_user.id),
        entity_types=payload.entity_types,
        project_id=None,
        project_ids=payload.project_ids,
        organization_id=payload.organization_id,
        use_semantic=payload.use_semantic,
        page=payload.page,
        page_size=payload.page_size,
    )


@router.get(
    "/suggestions",
    summary="Search autocomplete suggestions",
)
async def search_suggestions(
    q: str = Query(min_length=1, max_length=200),
    entity_types: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=20),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return quick autocomplete suggestions for the search bar."""
    svc = SearchService(db)
    type_list = [t.strip() for t in entity_types.split(",")] if entity_types else None
    return await svc.get_suggestions(
        query=q,
        user_id=str(current_user.id),
        entity_types=type_list,
        limit=limit,
    )


@router.get(
    "/similar/{entity_type}/{entity_id}",
    summary="Find similar items using semantic similarity",
)
async def find_similar(
    entity_type: str,
    entity_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find semantically similar requirements, stories, or other entities."""
    svc = SearchService(db)
    return await svc.find_similar(
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=str(current_user.id),
        limit=limit,
    )
