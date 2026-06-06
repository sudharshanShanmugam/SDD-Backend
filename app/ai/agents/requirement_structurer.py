"""
Requirement Structurer Agent

Takes raw extracted requirements and structures them into organized domains,
resolves conflicts, identifies missing requirements, and assigns business value.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.requirement_prompts import RequirementPrompts

logger = logging.getLogger(__name__)


class StructuredRequirement(BaseModel):
    """A fully structured and analyzed requirement."""
    id: str
    title: str
    description: str
    type: str = "functional"
    category: str
    priority: str
    business_value: int = 5
    technical_complexity: int = 5
    dependencies: List[str] = Field(default_factory=list)
    conflicts_with: List[str] = Field(default_factory=list)
    implied_by: List[str] = Field(default_factory=list)
    domain: str = ""
    tags: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)


class Domain(BaseModel):
    """A logical grouping of requirements."""
    name: str
    description: str
    requirements: List[str] = Field(default_factory=list)
    priority_order: List[str] = Field(default_factory=list)


class Conflict(BaseModel):
    """A detected conflict between requirements."""
    requirement_ids: List[str]
    conflict_description: str
    resolution_suggestion: str


class MissingRequirement(BaseModel):
    """A suggested missing requirement."""
    suggested_title: str
    reason: str
    implied_by: List[str] = Field(default_factory=list)
    priority: str = "should_have"


class RequirementSummary(BaseModel):
    """Summary statistics for the structured requirements."""
    total_functional: int = 0
    total_non_functional: int = 0
    total_constraints: int = 0
    must_have_count: int = 0
    conflict_count: int = 0
    ambiguity_count: int = 0


class StructuredRequirementsResult(BaseModel):
    """Complete structured requirements result."""
    domains: List[Dict[str, Any]] = Field(default_factory=list)
    structured_requirements: List[Dict[str, Any]] = Field(default_factory=list)
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    missing_requirements: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


class RequirementStructurerAgent(BaseAgent[StructuredRequirementsResult]):
    """
    Structures and analyzes extracted requirements.

    Takes raw requirements and:
    - Groups them into logical domains/modules
    - Detects conflicts and suggests resolutions
    - Identifies implied but missing requirements
    - Scores business value and technical complexity
    - Builds a dependency graph
    """

    def __init__(self):
        super().__init__(
            task_name="requirement_structuring",
            output_schema=StructuredRequirementsResult,
            enable_rag=True,
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        return RequirementPrompts.get_structuring_template()

    async def _parse_output(self, raw_output: str) -> StructuredRequirementsResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return StructuredRequirementsResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse requirement structuring output: %s", e)
            return StructuredRequirementsResult()

    async def structure(
        self,
        raw_requirements: Dict[str, Any],
        existing_requirements: Optional[List[Dict]] = None,
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Structure and analyze raw requirements.

        Args:
            raw_requirements: Output from RequirementExtractorAgent
            existing_requirements: Existing requirements in the system (for dedup)
            rag_results: Similar past requirements for context
            organization_id: Organization for multi-tenancy

        Returns:
            AgentResult with StructuredRequirementsResult
        """
        input_data = {
            "raw_requirements_json": json.dumps(raw_requirements, indent=2),
            "existing_requirements_json": json.dumps(
                existing_requirements or [], indent=2
            ),
        }

        return await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )
