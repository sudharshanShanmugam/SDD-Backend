"""
Documentation Agent

Generates technical documentation from project artifacts including
architecture docs, API guides, integration guides, and developer docs.
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


DOCUMENTATION_PROMPT = SystemPrompts.SOFTWARE_ARCHITECT + """

## Documentation Writing Guidelines
- Write for the target audience (developers, architects, end users)
- Use clear headings, numbered steps, and code examples
- Include architecture decision records (ADRs) for significant choices
- Document all APIs, data models, and integration points
- Write in Markdown format
- Include diagrams described in Mermaid syntax where helpful

## Output Schema
{
  "documentation": {
    "type": "string (architecture|api_guide|integration_guide|developer_guide|user_guide)",
    "title": "string",
    "version": "string",
    "audience": "string",
    "sections": [
      {
        "heading": "string",
        "level": 1,
        "content": "string (markdown)",
        "subsections": []
      }
    ],
    "diagrams": [
      {
        "title": "string",
        "type": "mermaid",
        "code": "string"
      }
    ],
    "table_of_contents": ["string"]
  }
}"""


class DocumentationSection(BaseModel):
    heading: str
    level: int = 1
    content: str
    subsections: List[Dict[str, Any]] = Field(default_factory=list)


class Diagram(BaseModel):
    title: str
    type: str = "mermaid"
    code: str


class DocumentationResult(BaseModel):
    documentation: Dict[str, Any] = Field(default_factory=dict)


class DocumentationAgent(BaseAgent[DocumentationResult]):
    """
    Generates technical documentation from SDD artifacts.

    Can generate:
    - Architecture documentation with Mermaid diagrams
    - API integration guides
    - Developer onboarding guides
    - System design documents
    - Component library documentation
    """

    def __init__(self):
        super().__init__(
            task_name="documentation_generation",
            output_schema=DocumentationResult,
            enable_rag=True,
        )
        self._prompt_template: Optional[ChatPromptTemplate] = None

    def get_prompt_template(self) -> ChatPromptTemplate:
        if self._prompt_template is None:
            self._prompt_template = ChatPromptTemplate.from_messages([
                ("system", DOCUMENTATION_PROMPT),
                ("human", """## Documentation Request
Type: {doc_type}
Title: {doc_title}
Target Audience: {audience}

## Source Artifacts

### Epics
{epics_json}

### User Stories (Sample)
{stories_json}

### API Specification (if available)
{api_spec_summary}

### Architecture Context
{architecture_context}

{rag_context}

## Instructions
1. Generate comprehensive {doc_type} documentation
2. Write in clear, professional technical language
3. Include Mermaid diagrams for: system context, data flow, sequence diagrams
4. Include code examples with syntax highlighting
5. Structure with clear headings and table of contents
6. Respond ONLY with valid JSON"""),
            ])
        return self._prompt_template

    async def _parse_output(self, raw_output: str) -> DocumentationResult:
        json_str = self._extract_json_from_response(raw_output)
        try:
            data = json.loads(json_str)
            return DocumentationResult.model_validate(data)
        except Exception as e:
            logger.error("Failed to parse documentation output: %s", e)
            return DocumentationResult()

    async def generate(
        self,
        doc_type: str,
        doc_title: str,
        epics: List[Dict[str, Any]],
        stories: Optional[List[Dict[str, Any]]] = None,
        api_spec: Optional[Dict[str, Any]] = None,
        architecture_context: str = "",
        audience: str = "software engineers",
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Generate documentation.

        Args:
            doc_type: Type of documentation to generate
            doc_title: Title for the documentation
            epics: Epics to document
            stories: Sample stories for context
            api_spec: API specification (if generating API docs)
            architecture_context: Architecture overview text
            audience: Target audience for the documentation
            rag_results: Similar past documentation for reference
            organization_id: Organization ID

        Returns:
            AgentResult with DocumentationResult
        """
        # Create API spec summary to reduce token usage
        api_spec_summary = "Not provided"
        if api_spec:
            paths = api_spec.get("paths", {})
            api_spec_summary = (
                f"{len(paths)} endpoints defined. "
                f"Paths: {', '.join(list(paths.keys())[:10])}"
            )

        input_data = {
            "doc_type": doc_type,
            "doc_title": doc_title,
            "audience": audience,
            "epics_json": json.dumps(epics, indent=2),
            "stories_json": json.dumps((stories or [])[:5], indent=2),  # Sample only
            "api_spec_summary": api_spec_summary,
            "architecture_context": architecture_context or "Standard microservices architecture",
        }

        return await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )
