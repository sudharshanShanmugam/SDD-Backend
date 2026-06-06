"""
Traceability Agent

Generates a complete requirement traceability matrix (RTM) linking
requirements → epics → stories → tasks → test cases.
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


TRACEABILITY_SYSTEM = SystemPrompts.BASE + """

You are a Requirements Manager building a traceability matrix.

## Traceability Matrix Purpose
The RTM ensures:
1. Every requirement is implemented in at least one epic/story
2. Every story traces back to at least one requirement
3. Every story has test cases covering its acceptance criteria
4. Nothing is built without a requirement justification

## Coverage Analysis
- **Forward Traceability**: Requirement → Epic → Story → Task → Test
- **Backward Traceability**: Test → Story → Epic → Requirement
- **Coverage Gaps**: Items missing links in either direction

## Output Schema
{
  "traceability_matrix": {
    "entries": [
      {
        "requirement_id": "FR-XXX",
        "requirement_title": "string",
        "requirement_priority": "string",
        "epics": [
          {
            "epic_id": "EPIC-XXX",
            "epic_title": "string"
          }
        ],
        "stories": [
          {
            "story_id": "US-XXX",
            "story_title": "string",
            "story_points": 0
          }
        ],
        "tasks": ["TASK-XXX"],
        "test_cases": ["TC-XXX"],
        "coverage_status": "covered|partial|not_covered",
        "gaps": ["string"]
      }
    ],
    "coverage_summary": {
      "total_requirements": 0,
      "fully_covered": 0,
      "partially_covered": 0,
      "not_covered": 0,
      "coverage_percentage": 0.0
    },
    "orphaned_stories": [
      {
        "story_id": "string",
        "story_title": "string",
        "reason": "string"
      }
    ],
    "orphaned_tests": [
      {
        "test_id": "string",
        "reason": "string"
      }
    ]
  }
}"""


class TraceabilityResult(BaseModel):
    traceability_matrix: Dict[str, Any] = Field(default_factory=dict)


class TraceabilityAgent(BaseAgent[TraceabilityResult]):
    """
    Generates a Requirement Traceability Matrix (RTM).

    Links all SDLC artifacts:
    Requirements → Epics → Stories → Tasks → Test Cases

    Identifies:
    - Requirements without implementation (coverage gaps)
    - Stories without requirement justification (orphaned stories)
    - Test cases without corresponding stories (orphaned tests)
    - Partial coverage where requirements are only partially addressed
    """

    def __init__(self):
        super().__init__(
            task_name="traceability",
            output_schema=TraceabilityResult,
            enable_rag=False,
        )
        self._prompt_template: Optional[ChatPromptTemplate] = None

    def get_prompt_template(self) -> ChatPromptTemplate:
        if self._prompt_template is None:
            self._prompt_template = ChatPromptTemplate.from_messages([
                ("system", TRACEABILITY_SYSTEM),
                ("human", """## Requirements
{requirements_json}

## Epics
{epics_json}

## Stories
{stories_json}

## Tasks
{tasks_json}

## Test Cases
{test_cases_json}

{rag_context}

## Instructions
1. Build the complete traceability matrix
2. Link each requirement to its epics, stories, tasks, and tests
3. Identify requirements with NO coverage (critical gaps)
4. Identify stories that don't trace back to any requirement
5. Calculate coverage percentage
6. Flag partial coverage (requirement has stories but no tests)
7. Respond ONLY with valid JSON"""),
            ])
        return self._prompt_template

    async def _parse_output(self, raw_output: str) -> TraceabilityResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return TraceabilityResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse traceability output: %s", e)
            return TraceabilityResult()

    async def generate_matrix(
        self,
        requirements: List[Dict[str, Any]],
        epics: List[Dict[str, Any]],
        stories: List[Dict[str, Any]],
        tasks: Optional[List[Dict[str, Any]]] = None,
        test_cases: Optional[List[Dict[str, Any]]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Generate the requirements traceability matrix.

        Args:
            requirements: All structured requirements
            epics: All generated epics
            stories: All generated user stories
            tasks: Optional engineering tasks
            test_cases: Optional test cases
            organization_id: Organization ID

        Returns:
            AgentResult with TraceabilityResult
        """
        input_data = {
            "requirements_json": json.dumps(requirements, indent=2),
            "epics_json": json.dumps(epics, indent=2),
            "stories_json": json.dumps(stories, indent=2),
            "tasks_json": json.dumps(tasks or [], indent=2),
            "test_cases_json": json.dumps(test_cases or [], indent=2),
        }

        result = await self.run(
            input_data=input_data,
            organization_id=organization_id,
        )

        if result.success and result.data:
            matrix = result.data.traceability_matrix
            summary = matrix.get("coverage_summary", {})
            not_covered = summary.get("not_covered", 0)

            if not_covered > 0:
                logger.warning(
                    "%d requirements have NO implementation coverage!",
                    not_covered,
                )

            logger.info(
                "Traceability matrix: %d requirements, %.1f%% coverage, "
                "%d orphaned stories",
                summary.get("total_requirements", 0),
                summary.get("coverage_percentage", 0),
                len(matrix.get("orphaned_stories", [])),
            )

        return result
