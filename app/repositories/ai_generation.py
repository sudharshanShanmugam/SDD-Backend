"""AIGeneration repository."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.core.constants import AIStatus
from app.models.ai_generation import AIGeneration
from app.repositories.base import BaseRepository


class AIGenerationRepository(BaseRepository[AIGeneration]):
    def __init__(self, db) -> None:
        super().__init__(db, AIGeneration)

    async def list_by_project(
        self,
        project_id: UUID,
        org_id: UUID,
        page: int = 1,
        page_size: int = 20,
        generation_type: Optional[str] = None,
        status: Optional[AIStatus] = None,
    ) -> tuple[list[AIGeneration], int]:
        from sqlalchemy import desc

        stmt = (
            select(AIGeneration)
            .where(AIGeneration.project_id == project_id)
            .where(AIGeneration.organization_id == org_id)
        )
        if generation_type:
            stmt = stmt.where(AIGeneration.generation_type == generation_type)
        if status:
            stmt = stmt.where(AIGeneration.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(desc(AIGeneration.created_at)).offset((page - 1) * page_size).limit(page_size)
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, total

    async def get_by_celery_task_id(
        self, task_id: str
    ) -> Optional[AIGeneration]:
        stmt = select(AIGeneration).where(AIGeneration.celery_task_id == task_id)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def mark_started(
        self, gen: AIGeneration, celery_task_id: Optional[str] = None
    ) -> AIGeneration:
        from datetime import datetime, timezone

        gen.status = AIStatus.PROCESSING
        gen.started_at = datetime.now(tz=timezone.utc).isoformat()
        if celery_task_id:
            gen.celery_task_id = celery_task_id
        await self.db.flush()
        return gen

    async def mark_completed(
        self,
        gen: AIGeneration,
        output_payload: dict,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        confidence_score: Optional[float] = None,
        latency_ms: Optional[int] = None,
    ) -> AIGeneration:
        from datetime import datetime, timezone

        gen.status = AIStatus.COMPLETED
        gen.completed_at = datetime.now(tz=timezone.utc).isoformat()
        gen.output_payload = output_payload
        gen.prompt_tokens = prompt_tokens
        gen.completion_tokens = completion_tokens
        gen.total_tokens = prompt_tokens + completion_tokens
        gen.cost_usd = cost_usd
        gen.confidence_score = confidence_score
        gen.latency_ms = latency_ms
        await self.db.flush()
        await self.db.refresh(gen)
        return gen

    async def mark_failed(
        self, gen: AIGeneration, error_message: str
    ) -> AIGeneration:
        gen.status = AIStatus.FAILED
        gen.error_message = error_message
        gen.retry_count += 1
        await self.db.flush()
        return gen

    async def get_total_tokens_for_org(self, org_id: UUID) -> int:
        stmt = (
            select(func.coalesce(func.sum(AIGeneration.total_tokens), 0))
            .where(AIGeneration.organization_id == org_id)
            .where(AIGeneration.status == AIStatus.COMPLETED)
        )
        return (await self.db.execute(stmt)).scalar_one()
