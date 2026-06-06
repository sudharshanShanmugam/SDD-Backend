"""
Sprint Planner Agent

AI-powered sprint planning that respects velocity, dependencies,
and balances workload across team members and skill areas.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.sprint_prompts import SprintPrompts

logger = logging.getLogger(__name__)


class SprintStory(BaseModel):
    story_id: str
    story_title: str
    story_points: int
    rationale: str = ""


class SprintRisk(BaseModel):
    description: str
    probability: str = "medium"
    impact: str = "medium"
    mitigation: str = ""


class SprintDependency(BaseModel):
    story_id: str
    depends_on_story_id: str
    description: str = ""


class Sprint(BaseModel):
    sprint_number: int
    sprint_name: str
    goal: str
    start_date: str
    end_date: str
    capacity_points: int
    committed_points: int
    stories: List[Dict[str, Any]] = Field(default_factory=list)
    milestones: List[str] = Field(default_factory=list)
    risks: List[Dict[str, Any]] = Field(default_factory=list)
    dependencies: List[Dict[str, Any]] = Field(default_factory=list)
    tech_debt_items: List[str] = Field(default_factory=list)


class CapacityAnalysis(BaseModel):
    total_available_points: int
    total_committed_points: int
    utilization_percent: float
    buffer_points: int


class ReleaseMilestone(BaseModel):
    name: str
    date: str
    stories_completed: List[str] = Field(default_factory=list)
    deliverables: List[str] = Field(default_factory=list)


class SprintPlanResult(BaseModel):
    sprint_plan: Dict[str, Any] = Field(default_factory=dict)


class SprintPlannerAgent(BaseAgent[SprintPlanResult]):
    """
    Plans sprints using AI reasoning about story dependencies,
    team capacity, and delivery risk.

    Input:
        - User stories with story points and dependencies
        - Team configuration (size, velocity, capacity breakdown)
        - Project constraints and dates

    Output:
        SprintPlanResult with:
        - Sprint assignments with goals and milestones
        - Risk analysis per sprint
        - Capacity utilization analysis
        - Release milestone schedule
        - Unplanned stories with explanations
    """

    def __init__(self):
        super().__init__(
            task_name="sprint_planning",
            output_schema=SprintPlanResult,
            enable_rag=False,  # Sprint planning is highly project-specific
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        return SprintPrompts.get_planning_template()

    async def _parse_output(self, raw_output: str) -> SprintPlanResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return SprintPlanResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse sprint plan output: %s", e)
            return SprintPlanResult()

    async def plan(
        self,
        stories: List[Dict[str, Any]],
        team_size: int = 5,
        sprint_length_weeks: int = 2,
        sprint_velocity: int = 40,
        num_sprints: int = 6,
        start_date: Optional[str] = None,
        capacity_breakdown: Optional[Dict[str, Any]] = None,
        constraints: Optional[List[str]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Create a sprint plan for the given user stories.

        Args:
            stories: List of user story dicts with story_points and dependencies
            team_size: Number of developers
            sprint_length_weeks: Sprint duration in weeks
            sprint_velocity: Total story points per sprint
            num_sprints: Number of sprints to plan
            start_date: Project start date (YYYY-MM-DD), defaults to today
            capacity_breakdown: Team capacity by role/skill
            constraints: Business/technical constraints on planning
            organization_id: Organization ID

        Returns:
            AgentResult with SprintPlanResult
        """
        if start_date is None:
            start_date = date.today().isoformat()

        default_capacity = {
            "backend_engineers": max(1, team_size // 3),
            "frontend_engineers": max(1, team_size // 3),
            "fullstack_engineers": team_size - 2 * max(1, team_size // 3),
            "sprint_ceremony_overhead_points": int(sprint_velocity * 0.1),
            "bug_fix_buffer_points": int(sprint_velocity * 0.1),
        }

        input_data = {
            "stories_json": json.dumps(stories, indent=2),
            "team_size": str(team_size),
            "sprint_length_weeks": str(sprint_length_weeks),
            "sprint_velocity": str(sprint_velocity),
            "num_sprints": str(num_sprints),
            "start_date": start_date,
            "capacity_breakdown_json": json.dumps(
                capacity_breakdown or default_capacity, indent=2
            ),
            "constraints_json": json.dumps(constraints or [], indent=2),
        }

        result = await self.run(
            input_data=input_data,
            organization_id=organization_id,
        )

        if result.success and result.data:
            plan = result.data.sprint_plan
            sprints = plan.get("sprints", [])
            unplanned = plan.get("unplanned_stories", [])
            logger.info(
                "Sprint plan created: %d sprints, %d unplanned stories",
                len(sprints),
                len(unplanned),
            )

        return result
