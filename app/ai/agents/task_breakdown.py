"""
Task Breakdown Agent

Breaks user stories into concrete engineering tasks with
technical details, time estimates, and assignee recommendations.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.task_prompts import TaskPrompts

logger = logging.getLogger(__name__)


class TechnicalDetails(BaseModel):
    files_to_modify: List[str] = Field(default_factory=list)
    new_files: List[str] = Field(default_factory=list)
    api_endpoints: List[str] = Field(default_factory=list)
    database_changes: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    environment_variables: List[str] = Field(default_factory=list)


class Subtask(BaseModel):
    title: str
    estimated_hours: float = 1.0


class EngineeringTask(BaseModel):
    id: str
    story_id: str
    title: str
    description: str
    category: str  # BACKEND|FRONTEND|DATABASE|DEVOPS|TESTING|DOCUMENTATION
    estimated_hours: float
    complexity: str = "medium"
    technical_details: Dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    assignee_role: str = "fullstack"
    labels: List[str] = Field(default_factory=list)
    subtasks: List[Dict[str, Any]] = Field(default_factory=list)


class TaskBreakdownSummary(BaseModel):
    total_tasks: int = 0
    total_hours: float = 0.0
    by_category: Dict[str, float] = Field(default_factory=dict)


class TaskBreakdownResult(BaseModel):
    tasks: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


class TaskBreakdownAgent(BaseAgent[TaskBreakdownResult]):
    """
    Decomposes user stories into engineering tasks.

    Generates specific, time-bounded tasks covering:
    - Backend implementation (APIs, services, business logic)
    - Frontend implementation (components, pages, state)
    - Database changes (schemas, migrations, indexes)
    - DevOps changes (infrastructure, CI/CD)
    - Testing (unit, integration, E2E)
    - Documentation (API docs, code comments)
    """

    def __init__(self):
        super().__init__(
            task_name="task_breakdown",
            output_schema=TaskBreakdownResult,
            enable_rag=True,
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        return TaskPrompts.get_breakdown_template()

    async def _parse_output(self, raw_output: str) -> TaskBreakdownResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return TaskBreakdownResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse task breakdown output: %s", e)
            return TaskBreakdownResult()

    async def breakdown(
        self,
        story: Dict[str, Any],
        tech_stack: Optional[Dict[str, Any]] = None,
        architecture: str = "monolith",
        database_type: str = "PostgreSQL",
        frontend_framework: str = "React",
        codebase_context: str = "",
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Break a user story into engineering tasks.

        Args:
            story: User story dict from StoryGeneratorAgent
            tech_stack: Technology stack configuration
            architecture: System architecture type
            database_type: Database being used
            frontend_framework: Frontend framework
            codebase_context: Summary of relevant existing code
            rag_results: Similar past task breakdowns for reference
            organization_id: Organization ID

        Returns:
            AgentResult with TaskBreakdownResult
        """
        default_tech_stack = {
            "backend": "Python/FastAPI",
            "frontend": frontend_framework,
            "database": database_type,
            "cache": "Redis",
            "message_queue": "None",
            "containerization": "Docker",
            "ci_cd": "GitHub Actions",
        }

        input_data = {
            "story_json": json.dumps(story, indent=2),
            "tech_stack_json": json.dumps(tech_stack or default_tech_stack, indent=2),
            "architecture": architecture,
            "database_type": database_type,
            "frontend_framework": frontend_framework,
            "codebase_context": codebase_context or "No codebase context provided",
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            task_result: TaskBreakdownResult = result.data
            total_hours = task_result.summary.get("total_hours", 0)
            logger.info(
                "Story %s broken into %d tasks, ~%.1f hours",
                story.get("id", "?"),
                len(task_result.tasks),
                total_hours,
            )

        return result
