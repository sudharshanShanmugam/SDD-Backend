"""
Epic Generator Agent

Generates epics from structured requirements, grouping related requirements
into cohesive, business-value-driven epics with acceptance criteria and estimates.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.epic_prompts import EpicPrompts

logger = logging.getLogger(__name__)


class Epic(BaseModel):
    """An epic representing a significant capability."""
    id: str
    title: str
    description: str
    business_value: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    priority: str = "should_have"
    effort_estimate: str = "M"
    story_points_range: Dict[str, int] = Field(default_factory=lambda: {"min": 0, "max": 0})
    requirement_ids: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    domain: str = ""
    target_personas: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    definition_of_done: List[str] = Field(default_factory=list)


class EpicGenerationResult(BaseModel):
    """Complete epic generation result."""
    epics: List[Dict[str, Any]] = Field(default_factory=list)
    grouping_rationale: str = ""
    coverage_gaps: List[str] = Field(default_factory=list)
    total_estimated_sprints: int = 0


class EpicGeneratorAgent(BaseAgent[EpicGenerationResult]):
    """
    Generates epics from structured requirements.

    Input:
        - Structured requirements (from RequirementStructurerAgent)
        - Project context (name, team size, sprint length, domain)

    Output:
        EpicGenerationResult with:
        - List of epics with acceptance criteria, estimates, and dependencies
        - Grouping rationale explaining why requirements were grouped
        - Coverage gaps (requirements not assigned to any epic)
        - Total estimated sprints for delivery
    """

    def __init__(self):
        super().__init__(
            task_name="epic_generation",
            output_schema=EpicGenerationResult,
            enable_rag=True,
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        return EpicPrompts.get_generation_template()

    async def _parse_output(self, raw_output: str) -> EpicGenerationResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return EpicGenerationResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse epic generation output: %s", e)
            return EpicGenerationResult()

    async def generate(
        self,
        structured_requirements: Dict[str, Any],
        project_name: str = "Project",
        team_size: int = 5,
        sprint_length_weeks: int = 2,
        domain: str = "general",
        target_users: str = "end users",
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Generate epics from structured requirements.

        Args:
            structured_requirements: Output from RequirementStructurerAgent
            project_name: Name of the project
            team_size: Number of developers on the team
            sprint_length_weeks: Length of each sprint in weeks
            domain: Business domain for context
            target_users: Description of primary user personas
            rag_results: Similar past epics for reference
            organization_id: Organization ID

        Returns:
            AgentResult with EpicGenerationResult
        """
        input_data = {
            "requirements_json": json.dumps(structured_requirements, indent=2),
            "project_name": project_name,
            "team_size": str(team_size),
            "sprint_length_weeks": str(sprint_length_weeks),
            "domain": domain,
            "target_users": target_users,
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            epic_result: EpicGenerationResult = result.data
            logger.info(
                "Generated %d epics, %d coverage gaps, ~%d sprints",
                len(epic_result.epics),
                len(epic_result.coverage_gaps),
                epic_result.total_estimated_sprints,
            )

        return result
