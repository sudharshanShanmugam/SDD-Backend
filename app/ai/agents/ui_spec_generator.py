"""
UI/UX Specification Generator Agent

Generates implementation-ready UI specifications from stories,
including component hierarchy, state management, interactions, and accessibility.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.ai.agents.base_agent import BaseAgent, AgentResult
from app.ai.prompts.spec_prompts import SpecPrompts

logger = logging.getLogger(__name__)


class UISpec(BaseModel):
    """Complete UI specification for a feature."""
    ui_spec: Dict[str, Any] = Field(default_factory=dict)


class UISpecGeneratorAgent(BaseAgent[UISpec]):
    """
    Generates implementation-ready UI/UX specifications.

    Input:
        - User stories for a feature/epic
        - Design system configuration
        - Existing components
        - User personas

    Output:
        UISpec with:
        - Page/view definitions
        - Component hierarchy using atomic design
        - Props, state, and interaction specifications
        - Accessibility attributes (WCAG 2.1 AA)
        - Loading, error, and empty states
        - Data flow definitions
        - Form validation rules
    """

    def __init__(self):
        super().__init__(
            task_name="ui_spec_generation",
            output_schema=UISpec,
            enable_rag=True,
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        return SpecPrompts.get_ui_spec_template()

    async def _parse_output(self, raw_output: str) -> UISpec:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return UISpec.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse UI spec output: %s", e)
            return UISpec()

    async def generate(
        self,
        stories: List[Dict[str, Any]],
        component_library: str = "shadcn/ui",
        design_tokens: Optional[Dict[str, Any]] = None,
        existing_components: Optional[List[str]] = None,
        personas: Optional[List[Dict]] = None,
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Generate UI specification for the given stories.

        Args:
            stories: User stories defining the UI feature
            component_library: UI component library being used
            design_tokens: Design token configuration (colors, spacing, etc.)
            existing_components: List of reusable components already in codebase
            personas: User personas for accessibility/UX context
            rag_results: Similar past UI specs for reference
            organization_id: Organization ID

        Returns:
            AgentResult with UISpec
        """
        default_tokens = {
            "colors": {
                "primary": "#2563EB",
                "secondary": "#64748B",
                "error": "#DC2626",
                "success": "#16A34A",
                "warning": "#D97706",
            },
            "spacing": "4px base unit",
            "border_radius": "4px default, 8px cards",
            "typography": {
                "heading": "Inter, sans-serif",
                "body": "Inter, sans-serif",
                "code": "JetBrains Mono, monospace",
            },
        }

        input_data = {
            "stories_json": json.dumps(stories, indent=2),
            "component_library": component_library,
            "design_tokens_json": json.dumps(design_tokens or default_tokens, indent=2),
            "existing_components_json": json.dumps(existing_components or [], indent=2),
            "personas_json": json.dumps(
                personas or [
                    {"name": "End User", "accessibility_needs": "standard"},
                    {"name": "Admin", "accessibility_needs": "standard"},
                ],
                indent=2,
            ),
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            ui_spec = result.data.ui_spec
            components = ui_spec.get("components", [])
            logger.info(
                "Generated UI spec with %d components for %d stories",
                len(components),
                len(stories),
            )

        return result
