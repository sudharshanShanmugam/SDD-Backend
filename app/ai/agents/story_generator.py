"""
Story Generator Agent

Generates user stories from epics following INVEST criteria.
Stories include Gherkin acceptance criteria, story points, and dependencies.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.story_prompts import StoryPrompts

logger = logging.getLogger(__name__)


class AcceptanceCriterion(BaseModel):
    """Gherkin-format acceptance criterion."""
    id: str
    scenario: str
    given: str
    when: str
    then: str


class INVESTIssue(BaseModel):
    """INVEST criterion violation."""
    story_id: str
    criterion: str
    issue: str
    suggestion: str


class UserStory(BaseModel):
    """A user story following the INVEST criteria."""
    id: str
    epic_id: str
    title: str
    user_story: str
    persona: str
    goal: str
    benefit: str
    acceptance_criteria: List[Dict[str, Any]] = Field(default_factory=list)
    story_points: int = 3
    priority: str = "medium"
    labels: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    blocked_by: List[str] = Field(default_factory=list)
    requirement_ids: List[str] = Field(default_factory=list)
    notes: str = ""
    definition_of_done: List[str] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)


class UserStoryList(BaseModel):
    """Complete story generation result."""
    stories: List[Dict[str, Any]] = Field(default_factory=list)
    invest_analysis: Dict[str, Any] = Field(default_factory=dict)


class StoryGeneratorAgent(BaseAgent[UserStoryList]):
    """
    Generates user stories from an epic.

    Input:
        - Epic details with acceptance criteria
        - Related requirements
        - Team context (personas, velocity)

    Output:
        UserStoryList with INVEST-compliant stories, each having:
        - Standard user story format (As a / I want / So that)
        - Gherkin acceptance criteria
        - Story point estimates (Fibonacci)
        - Dependencies and blockers
        - Definition of done
        - Explicit out-of-scope items
    """

    def __init__(self):
        super().__init__(
            task_name="story_generation",
            output_schema=UserStoryList,
            enable_rag=True,
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        return StoryPrompts.get_generation_template()

    async def _parse_output(self, raw_output: str) -> UserStoryList:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return UserStoryList.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse story generation output: %s", e)
            return UserStoryList()

    async def generate_for_epic(
        self,
        epic: Dict[str, Any],
        requirements: List[Dict[str, Any]],
        personas: Optional[List[Dict]] = None,
        sprint_velocity: int = 40,
        sprint_length_weeks: int = 2,
        existing_stories: Optional[List[Dict]] = None,
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Generate user stories for a specific epic.

        Args:
            epic: The epic dict from EpicGeneratorAgent
            requirements: Structured requirements related to this epic
            personas: User personas for the project
            sprint_velocity: Team velocity in story points per sprint
            sprint_length_weeks: Length of sprint in weeks
            existing_stories: Existing stories (for deduplication)
            rag_results: Similar past stories for reference
            organization_id: Organization ID

        Returns:
            AgentResult with UserStoryList
        """
        default_personas = [
            {"name": "End User", "description": "Primary system user"},
            {"name": "Administrator", "description": "System administrator"},
        ]

        input_data = {
            "epic_json": json.dumps(epic, indent=2),
            "requirements_json": json.dumps(requirements, indent=2),
            "existing_stories_json": json.dumps(existing_stories or [], indent=2),
            "personas_json": json.dumps(personas or default_personas, indent=2),
            "sprint_velocity": str(sprint_velocity),
            "sprint_length_weeks": str(sprint_length_weeks),
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            story_list: UserStoryList = result.data
            stories = story_list.stories

            # Log INVEST violations
            invest_issues = story_list.invest_analysis.get("issues", [])
            if invest_issues:
                logger.warning(
                    "INVEST violations in %d stories for epic %s",
                    len(invest_issues),
                    epic.get("id", "?"),
                )

            # Log oversized stories
            large_stories = [
                s for s in stories
                if isinstance(s, dict) and s.get("story_points", 0) > 13
            ]
            if large_stories:
                logger.warning(
                    "%d stories exceed 13 points and should be split",
                    len(large_stories),
                )

            logger.info(
                "Generated %d stories for epic %s",
                len(stories),
                epic.get("id", "?"),
            )

        return result

    async def generate_for_all_epics(
        self,
        epics: List[Dict[str, Any]],
        requirements: List[Dict[str, Any]],
        personas: Optional[List[Dict]] = None,
        sprint_velocity: int = 40,
        sprint_length_weeks: int = 2,
        organization_id: Optional[str] = None,
    ) -> Dict[str, AgentResult]:
        """
        Generate stories for all epics concurrently.

        Returns a dict mapping epic_id -> AgentResult.
        """
        import asyncio

        async def generate_single(epic: Dict) -> tuple[str, AgentResult]:
            # Filter requirements relevant to this epic
            epic_req_ids = set(epic.get("requirement_ids", []))
            relevant_reqs = [
                r for r in requirements
                if isinstance(r, dict) and r.get("id") in epic_req_ids
            ] or requirements  # Fall back to all if no mapping

            result = await self.generate_for_epic(
                epic=epic,
                requirements=relevant_reqs,
                personas=personas,
                sprint_velocity=sprint_velocity,
                sprint_length_weeks=sprint_length_weeks,
                organization_id=organization_id,
            )
            return epic.get("id", "unknown"), result

        tasks = [generate_single(epic) for epic in epics]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: Dict[str, AgentResult] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error("Story generation task failed: %s", result)
            else:
                epic_id, agent_result = result
                output[epic_id] = agent_result

        return output
