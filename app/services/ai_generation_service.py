"""
AI Generation Service.
Manages AI generation run records and prompt templates.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AIGenerationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_generations(
        self,
        user_id: str,
        project_id: str | None,
        workflow_type: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        from sqlalchemy import text

        conditions = ["1=1"]
        params: dict = {}

        if project_id:
            conditions.append("project_id = :project_id")
            params["project_id"] = project_id
        if workflow_type:
            conditions.append("workflow_type = :workflow_type")
            params["workflow_type"] = workflow_type
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)
        try:
            result = await self.db.execute(
                text(f"""
                    SELECT run_id, workflow_type, entity_type, entity_id,
                           status, initiated_by, created_at, error_message
                    FROM ai_generations
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {**params, "limit": page_size, "offset": (page - 1) * page_size},
            )
            items = [dict(row._mapping) for row in result.all()]
            count_result = await self.db.execute(
                text(f"SELECT COUNT(*) FROM ai_generations WHERE {where}"),
                params,
            )
            total = count_result.scalar_one() or 0
        except Exception as exc:
            logger.warning("ai_generations table not available: %s", exc)
            items, total = [], 0

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def save_prompt_template(
        self,
        name: str,
        workflow_type: str,
        prompt_text: str,
        variables: list[str] | None,
        is_active: bool,
        description: str | None,
        created_by: str,
    ) -> dict:
        from sqlalchemy import text
        import json

        template_id = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc).isoformat()

        try:
            await self.db.execute(
                text("""
                    INSERT INTO ai_prompt_templates
                        (id, name, workflow_type, prompt_text, variables, is_active, description, created_by, created_at)
                    VALUES
                        (:id, :name, :workflow_type, :prompt_text, :variables::jsonb, :is_active, :description, :created_by, :created_at)
                    ON CONFLICT (name, workflow_type) DO UPDATE SET
                        prompt_text = EXCLUDED.prompt_text,
                        variables = EXCLUDED.variables,
                        is_active = EXCLUDED.is_active,
                        description = EXCLUDED.description,
                        updated_at = NOW()
                """),
                {
                    "id": template_id,
                    "name": name,
                    "workflow_type": workflow_type,
                    "prompt_text": prompt_text,
                    "variables": json.dumps(variables or []),
                    "is_active": is_active,
                    "description": description,
                    "created_by": created_by,
                    "created_at": now,
                },
            )
            await self.db.commit()
        except Exception as exc:
            logger.warning("Failed to save prompt template: %s", exc)

        return {
            "id": template_id,
            "name": name,
            "workflow_type": workflow_type,
            "is_active": is_active,
            "created_at": now,
        }

    async def list_prompt_templates(
        self,
        workflow_type: str | None,
        is_active: bool | None,
    ) -> list:
        from sqlalchemy import text

        conditions = ["1=1"]
        params: dict = {}
        if workflow_type:
            conditions.append("workflow_type = :workflow_type")
            params["workflow_type"] = workflow_type
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active

        where = " AND ".join(conditions)
        try:
            result = await self.db.execute(
                text(f"SELECT * FROM ai_prompt_templates WHERE {where} ORDER BY name"),
                params,
            )
            return [dict(row._mapping) for row in result.all()]
        except Exception:
            return []

    async def get_prompt_template(self, prompt_id: str) -> dict | None:
        from sqlalchemy import text
        try:
            result = await self.db.execute(
                text("SELECT * FROM ai_prompt_templates WHERE id = :id"),
                {"id": prompt_id},
            )
            row = result.one_or_none()
            return dict(row._mapping) if row else None
        except Exception:
            return None

    async def delete_prompt_template(self, prompt_id: str) -> None:
        from sqlalchemy import text
        try:
            await self.db.execute(
                text("DELETE FROM ai_prompt_templates WHERE id = :id"),
                {"id": prompt_id},
            )
            await self.db.commit()
        except Exception as exc:
            logger.warning("Failed to delete prompt template: %s", exc)
