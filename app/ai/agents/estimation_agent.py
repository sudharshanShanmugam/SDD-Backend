"""
Estimation Agent

AI-based story point and effort estimation using historical data,
complexity analysis, and team context.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.system_prompts import SystemPrompts

logger = logging.getLogger(__name__)


ESTIMATION_SYSTEM = SystemPrompts.TECH_LEAD + """

## Estimation Methodology
Use a combination of:
1. **Complexity Analysis**: How many system layers are affected?
2. **Uncertainty Analysis**: How well understood is the solution?
3. **Size Comparison**: How does this compare to a known reference story?
4. **Risk Analysis**: What unknowns could increase effort?
5. **Historical Calibration**: What do similar past stories tell us?

## Fibonacci Story Points
1 - Trivial (cosmetic change, config update)
2 - Simple (single component, clear solution)
3 - Small (1-2 components, minor complexity)
5 - Medium (multiple components, some uncertainty)
8 - Large (cross-cutting concern, significant complexity)
13 - Very Large (architectural change, high uncertainty - consider splitting)
21 - Epic-level (must be split before sprint planning)

## Output Schema
{
  "estimations": [
    {
      "story_id": "string",
      "story_title": "string",
      "recommended_points": 0,
      "confidence": "high|medium|low",
      "rationale": "string",
      "complexity_factors": {
        "technical_complexity": 1,
        "uncertainty": 1,
        "dependencies": 1,
        "cross_cutting": false
      },
      "effort_breakdown": {
        "backend_hours": 0,
        "frontend_hours": 0,
        "testing_hours": 0,
        "review_hours": 0,
        "total_hours": 0
      },
      "alternative_estimates": {
        "optimistic": 0,
        "pessimistic": 0
      },
      "split_recommendation": null
    }
  ],
  "estimation_summary": {
    "total_points": 0,
    "total_hours": 0,
    "average_confidence": "string",
    "stories_needing_split": ["US-XXX"],
    "velocity_based_sprints": 0
  }
}"""


class EstimationResult(BaseModel):
    estimations: List[Dict[str, Any]] = Field(default_factory=list)
    estimation_summary: Dict[str, Any] = Field(default_factory=dict)


class EstimationAgent(BaseAgent[EstimationResult]):
    """
    Provides AI-based story point estimation with confidence scoring.

    Uses complexity analysis, historical calibration, and uncertainty
    modeling to produce calibrated Fibonacci story point estimates.

    Can also identify stories that should be split before estimation.
    """

    def __init__(self):
        super().__init__(
            task_name="estimation",
            output_schema=EstimationResult,
            enable_rag=True,  # Use historical stories for calibration
        )
        self._prompt_template: Optional[ChatPromptTemplate] = None

    def get_prompt_template(self) -> ChatPromptTemplate:
        if self._prompt_template is None:
            self._prompt_template = ChatPromptTemplate.from_messages([
                ("system", ESTIMATION_SYSTEM),
                ("human", """## Stories to Estimate
{stories_json}

## Reference Stories (historical calibration)
{reference_stories_json}

## Team Context
Team Composition: {team_composition}
Tech Stack: {tech_stack}
Codebase Maturity: {codebase_maturity}
Average Velocity: {average_velocity} points/sprint

{rag_context}

## Instructions
1. Estimate story points for each story using the Fibonacci scale
2. Provide detailed rationale for each estimate
3. Break down estimated hours by work type (backend/frontend/testing)
4. Flag stories with high uncertainty or that should be split
5. Include optimistic and pessimistic estimates for high-uncertainty stories
6. Calibrate estimates against the reference stories provided
7. Respond ONLY with valid JSON"""),
            ])
        return self._prompt_template

    async def _parse_output(self, raw_output: str) -> EstimationResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return EstimationResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse estimation output: %s", e)
            return EstimationResult()

    async def estimate(
        self,
        stories: List[Dict[str, Any]],
        reference_stories: Optional[List[Dict]] = None,
        team_composition: str = "3 backend, 2 frontend engineers",
        tech_stack: str = "Python/FastAPI, React, PostgreSQL",
        codebase_maturity: str = "mature",
        average_velocity: int = 40,
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Estimate story points for a set of stories.

        Args:
            stories: User stories to estimate
            reference_stories: Historical stories with known actual effort
            team_composition: Team composition description
            tech_stack: Technology stack
            codebase_maturity: How mature/documented the codebase is
            average_velocity: Team's average sprint velocity
            rag_results: Similar historical stories from vector store
            organization_id: Organization ID

        Returns:
            AgentResult with EstimationResult
        """
        input_data = {
            "stories_json": json.dumps(stories, indent=2),
            "reference_stories_json": json.dumps(reference_stories or [], indent=2),
            "team_composition": team_composition,
            "tech_stack": tech_stack,
            "codebase_maturity": codebase_maturity,
            "average_velocity": str(average_velocity),
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            est_result: EstimationResult = result.data
            summary = est_result.estimation_summary
            needs_split = summary.get("stories_needing_split", [])

            if needs_split:
                logger.warning(
                    "%d stories recommended for splitting: %s",
                    len(needs_split),
                    needs_split,
                )

            logger.info(
                "Estimation complete: %d stories, %d total points, ~%.0f hours",
                len(est_result.estimations),
                summary.get("total_points", 0),
                summary.get("total_hours", 0),
            )

        return result
