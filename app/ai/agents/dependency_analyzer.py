"""
Dependency Analyzer Agent

Analyzes dependencies between requirements, epics, stories, and tasks.
Identifies critical paths, dependency conflicts, and circular dependencies.
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


DEPENDENCY_SYSTEM = SystemPrompts.TECH_LEAD + """

## Dependency Analysis Task
Analyze the provided items and identify:
1. Explicit dependencies (A must be done before B)
2. Implicit dependencies (A and B need the same data model)
3. Circular dependencies (A → B → C → A) - these must be broken
4. Critical path (longest dependency chain)
5. Parallel execution opportunities

## Output Schema
{
  "dependency_graph": {
    "nodes": [
      {
        "id": "string",
        "title": "string",
        "type": "requirement|epic|story|task",
        "level": 0
      }
    ],
    "edges": [
      {
        "from": "string",
        "to": "string",
        "type": "string (blocks|requires|relates_to|implements)",
        "description": "string"
      }
    ]
  },
  "critical_path": ["string (ordered IDs)"],
  "circular_dependencies": [
    {
      "cycle": ["string"],
      "description": "string",
      "resolution": "string"
    }
  ],
  "parallel_groups": [
    {
      "group_name": "string",
      "items": ["string"],
      "can_start_after": ["string"]
    }
  ],
  "dependency_layers": [
    {
      "layer": 0,
      "items": ["string"],
      "description": "string (what this layer delivers)"
    }
  ],
  "analysis_summary": {
    "total_dependencies": 0,
    "circular_count": 0,
    "critical_path_length": 0,
    "parallelism_opportunities": 0
  }
}"""


class DependencyAnalysisResult(BaseModel):
    dependency_graph: Dict[str, Any] = Field(default_factory=dict)
    critical_path: List[str] = Field(default_factory=list)
    circular_dependencies: List[Dict[str, Any]] = Field(default_factory=list)
    parallel_groups: List[Dict[str, Any]] = Field(default_factory=list)
    dependency_layers: List[Dict[str, Any]] = Field(default_factory=list)
    analysis_summary: Dict[str, Any] = Field(default_factory=dict)


class DependencyAnalyzerAgent(BaseAgent[DependencyAnalysisResult]):
    """
    Analyzes and visualizes dependencies between SDLC artifacts.

    Produces:
    - Full dependency graph (nodes and edges)
    - Critical path for delivery planning
    - Detection of circular dependencies with resolution suggestions
    - Parallel execution opportunities for sprint planning
    - Layered dependency view for understanding delivery sequence
    """

    def __init__(self):
        super().__init__(
            task_name="dependency_analysis",
            output_schema=DependencyAnalysisResult,
            enable_rag=False,
        )
        self._prompt_template: Optional[ChatPromptTemplate] = None

    def get_prompt_template(self) -> ChatPromptTemplate:
        if self._prompt_template is None:
            self._prompt_template = ChatPromptTemplate.from_messages([
                ("system", DEPENDENCY_SYSTEM),
                ("human", """## Items to Analyze
{items_json}

## Existing Dependency Information
{existing_dependencies_json}

## Analysis Context
Project Type: {project_type}
Tech Stack: {tech_stack}

{rag_context}

## Instructions
1. Analyze all explicit dependencies (stated in the items)
2. Infer implicit dependencies based on shared resources/data
3. Detect any circular dependencies and propose breaking them
4. Identify items that can be worked in parallel
5. Build layered delivery sequence (layer 0 = no dependencies)
6. Identify the critical path (longest dependency chain)
7. Respond ONLY with valid JSON"""),
            ])
        return self._prompt_template

    async def _parse_output(self, raw_output: str) -> DependencyAnalysisResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return DependencyAnalysisResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse dependency analysis output: %s", e)
            return DependencyAnalysisResult()

    async def analyze(
        self,
        items: List[Dict[str, Any]],
        existing_dependencies: Optional[List[Dict]] = None,
        project_type: str = "web_application",
        tech_stack: str = "Python/FastAPI, React, PostgreSQL",
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Analyze dependencies among a set of SDLC items.

        Args:
            items: List of requirements, epics, stories, or tasks
            existing_dependencies: Pre-existing dependency relationships
            project_type: Type of project
            tech_stack: Technology stack
            organization_id: Organization ID

        Returns:
            AgentResult with DependencyAnalysisResult
        """
        input_data = {
            "items_json": json.dumps(items, indent=2),
            "existing_dependencies_json": json.dumps(
                existing_dependencies or [], indent=2
            ),
            "project_type": project_type,
            "tech_stack": tech_stack,
        }

        result = await self.run(
            input_data=input_data,
            organization_id=organization_id,
        )

        if result.success and result.data:
            analysis: DependencyAnalysisResult = result.data
            summary = analysis.analysis_summary

            if analysis.circular_dependencies:
                logger.warning(
                    "Found %d circular dependencies that need resolution",
                    len(analysis.circular_dependencies),
                )

            logger.info(
                "Dependency analysis: %d edges, %d layers, critical path length=%d",
                summary.get("total_dependencies", 0),
                len(analysis.dependency_layers),
                summary.get("critical_path_length", 0),
            )

        return result
