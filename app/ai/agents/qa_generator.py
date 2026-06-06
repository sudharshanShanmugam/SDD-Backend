"""
QA Generator Agent

Generates comprehensive test suites from user stories including:
- Functional test cases
- Edge cases and negative tests
- Accessibility tests (WCAG 2.1 AA)
- Performance tests
- Security tests
- Complete Playwright TypeScript and Cypress JavaScript test code
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.qa_prompts import QAPrompts

logger = logging.getLogger(__name__)


class TestStep(BaseModel):
    step_number: int
    action: str
    expected_result: str


class TestCase(BaseModel):
    id: str
    title: str
    type: str  # functional|edge_case|negative|accessibility|performance|security
    priority: str = "medium"
    preconditions: List[str] = Field(default_factory=list)
    test_steps: List[Dict[str, Any]] = Field(default_factory=list)
    expected_result: str
    test_data: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    automation_feasible: bool = True


class CoverageAnalysis(BaseModel):
    acceptance_criteria_covered: List[str] = Field(default_factory=list)
    coverage_percent: float = 0.0
    gaps: List[str] = Field(default_factory=list)


class TestSuite(BaseModel):
    story_id: str
    test_cases: List[Dict[str, Any]] = Field(default_factory=list)
    playwright_code: str = ""
    cypress_code: str = ""
    coverage_analysis: Dict[str, Any] = Field(default_factory=dict)


class QATestSuite(BaseModel):
    test_suite: Dict[str, Any] = Field(default_factory=dict)


class QAGeneratorAgent(BaseAgent[QATestSuite]):
    """
    Generates comprehensive QA test suites for user stories.

    Generates:
    - Manual test cases (functional, edge, negative, accessibility, security)
    - Complete Playwright TypeScript test file (ready to run)
    - Complete Cypress JavaScript test file (ready to run)
    - Coverage analysis against acceptance criteria

    Test case priorities:
    - Critical: Core happy path, auth tests
    - High: Major features, security tests
    - Medium: Edge cases, UX tests
    - Low: Minor variations, cosmetic tests
    """

    def __init__(self):
        super().__init__(
            task_name="qa_generation",
            output_schema=QATestSuite,
            enable_rag=True,
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        return QAPrompts.get_generation_template()

    async def _parse_output(self, raw_output: str) -> QATestSuite:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return QATestSuite.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse QA generation output: %s", e)
            return QATestSuite()

    async def generate(
        self,
        story: Dict[str, Any],
        acceptance_criteria: Optional[List[Dict]] = None,
        ui_spec: Optional[Dict[str, Any]] = None,
        api_spec: Optional[Dict[str, Any]] = None,
        frontend_framework: str = "React",
        e2e_framework: str = "playwright",
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Generate QA tests for a user story.

        Args:
            story: User story dict
            acceptance_criteria: Gherkin acceptance criteria list
            ui_spec: UI specification for the story (if available)
            api_spec: API specification for the story (if available)
            frontend_framework: Framework being used (React, Vue, Angular)
            e2e_framework: E2E test framework (playwright, cypress)
            rag_results: Similar past test suites for reference
            organization_id: Organization ID

        Returns:
            AgentResult with QATestSuite including test code
        """
        # Extract acceptance criteria from story if not provided
        if acceptance_criteria is None:
            acceptance_criteria = story.get("acceptance_criteria", [])

        input_data = {
            "story_json": json.dumps(story, indent=2),
            "acceptance_criteria_json": json.dumps(acceptance_criteria, indent=2),
            "ui_spec_json": json.dumps(ui_spec or {}, indent=2),
            "api_spec_json": json.dumps(api_spec or {}, indent=2),
            "frontend_framework": frontend_framework,
            "e2e_framework": e2e_framework,
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            test_suite = result.data.test_suite
            test_cases = test_suite.get("test_cases", [])
            coverage = test_suite.get("coverage_analysis", {})

            logger.info(
                "Generated %d test cases for story %s (coverage: %.0f%%)",
                len(test_cases),
                story.get("id", "?"),
                coverage.get("coverage_percent", 0),
            )

            # Log missing playwright/cypress code
            if not test_suite.get("playwright_code"):
                logger.warning(
                    "No Playwright code generated for story %s", story.get("id", "?")
                )
            if not test_suite.get("cypress_code"):
                logger.warning(
                    "No Cypress code generated for story %s", story.get("id", "?")
                )

        return result

    async def generate_regression_suite(
        self,
        stories: List[Dict[str, Any]],
        organization_id: Optional[str] = None,
    ) -> Dict[str, AgentResult]:
        """
        Generate test suites for multiple stories concurrently.
        Returns dict mapping story_id -> AgentResult.
        """
        import asyncio

        async def gen_single(story: Dict) -> tuple[str, AgentResult]:
            result = await self.generate(
                story=story,
                organization_id=organization_id,
            )
            return story.get("id", "unknown"), result

        tasks = [gen_single(s) for s in stories]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: Dict[str, AgentResult] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error("QA generation task failed: %s", result)
            else:
                story_id, agent_result = result
                output[story_id] = agent_result

        return output
