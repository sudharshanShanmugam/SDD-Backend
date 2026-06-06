"""
Release Notes Agent

Generates professional release notes from completed stories and epics.
Formats for multiple audiences: technical, business, and end-user.
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


RELEASE_NOTES_SYSTEM = SystemPrompts.BASE + """

You are a technical writer generating release notes for a software product.

## Release Notes Guidelines
- Write for the specified audience (technical/business/end-user)
- Group changes by: New Features, Improvements, Bug Fixes, Breaking Changes
- Highlight high-impact changes prominently
- Include migration notes for breaking changes
- Use active voice and present tense
- Be concise but specific

## Output Schema
{
  "release_notes": {
    "version": "string",
    "release_date": "string (YYYY-MM-DD)",
    "summary": "string (1-2 sentence release summary)",
    "highlights": ["string (key features/improvements)"],
    "sections": {
      "new_features": [
        {
          "title": "string",
          "description": "string",
          "story_ids": ["US-XXX"],
          "impact": "high|medium|low"
        }
      ],
      "improvements": [],
      "bug_fixes": [],
      "breaking_changes": [],
      "deprecations": []
    },
    "migration_guide": "string (markdown, null if no breaking changes)",
    "known_issues": ["string"],
    "contributors": ["string"]
  }
}"""


class ReleaseNotesResult(BaseModel):
    release_notes: Dict[str, Any] = Field(default_factory=dict)


class ReleaseNotesAgent(BaseAgent[ReleaseNotesResult]):
    """
    Generates release notes from completed stories and epics.

    Supports multiple audience formats:
    - technical: For developers (includes API changes, DB migrations)
    - business: For product/business stakeholders (features and KPIs)
    - end_user: For customers (what changed, how to use new features)
    """

    def __init__(self):
        super().__init__(
            task_name="release_notes_generation",
            output_schema=ReleaseNotesResult,
            enable_rag=False,
        )
        self._prompt_template: Optional[ChatPromptTemplate] = None

    def get_prompt_template(self) -> ChatPromptTemplate:
        if self._prompt_template is None:
            self._prompt_template = ChatPromptTemplate.from_messages([
                ("system", RELEASE_NOTES_SYSTEM),
                ("human", """## Release Information
Version: {version}
Release Date: {release_date}
Audience: {audience}

## Completed Stories in this Release
{completed_stories_json}

## Completed Epics in this Release
{completed_epics_json}

## Previous Release Notes (for context)
{previous_release_notes}

{rag_context}

## Instructions
1. Generate release notes for version {version}
2. Tailor language for the {audience} audience
3. Identify and highlight breaking changes with migration guidance
4. Group features logically by epic/domain
5. Be specific about what changed, not just that "improvements were made"
6. Respond ONLY with valid JSON"""),
            ])
        return self._prompt_template

    async def _parse_output(self, raw_output: str) -> ReleaseNotesResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return ReleaseNotesResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse release notes output: %s", e)
            return ReleaseNotesResult()

    async def generate(
        self,
        version: str,
        release_date: str,
        completed_stories: List[Dict[str, Any]],
        completed_epics: List[Dict[str, Any]],
        audience: str = "technical",
        previous_release_notes: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Generate release notes.

        Args:
            version: Version string (e.g., "2.1.0")
            release_date: Release date in YYYY-MM-DD format
            completed_stories: Stories completed in this release
            completed_epics: Epics completed in this release
            audience: Target audience (technical|business|end_user)
            previous_release_notes: Previous release notes for continuity
            organization_id: Organization ID

        Returns:
            AgentResult with ReleaseNotesResult
        """
        input_data = {
            "version": version,
            "release_date": release_date,
            "audience": audience,
            "completed_stories_json": json.dumps(completed_stories, indent=2),
            "completed_epics_json": json.dumps(completed_epics, indent=2),
            "previous_release_notes": previous_release_notes or "No previous release notes",
        }

        return await self.run(
            input_data=input_data,
            organization_id=organization_id,
        )
