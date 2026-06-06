"""
Epic Generation Prompts
"""

from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts.system_prompts import SystemPrompts


class EpicPrompts:
    """Prompts for epic generation."""

    SYSTEM = SystemPrompts.PRODUCT_OWNER + """

## Epic Generation Guidelines
- Each epic should represent a significant, coherent capability (2-4 sprints of work)
- Group requirements that deliver a cohesive user outcome
- Write clear acceptance criteria that define "done" for the epic
- Estimate effort in T-shirt sizes: XS(1-2 sprints), S(2-3), M(3-5), L(5-8), XL(8+)
- Assign MoSCoW priority based on business value and dependencies
- Include a clear business value statement for each epic

## Output Schema
Respond with valid JSON:
{
  "epics": [
    {
      "id": "EPIC-XXX",
      "title": "string (action-oriented, business-focused)",
      "description": "string (2-3 sentence explanation of scope and value)",
      "business_value": "string (why this epic matters to the business)",
      "acceptance_criteria": ["string (testable, specific criteria)"],
      "priority": "must_have|should_have|could_have|wont_have",
      "effort_estimate": "XS|S|M|L|XL",
      "story_points_range": {"min": 0, "max": 0},
      "requirement_ids": ["FR-XXX", "NFR-XXX"],
      "dependencies": ["EPIC-XXX"],
      "tags": ["string"],
      "domain": "string",
      "target_personas": ["string"],
      "risks": ["string"],
      "definition_of_done": ["string"]
    }
  ],
  "grouping_rationale": "string (explain how requirements were grouped)",
  "coverage_gaps": ["string (requirements not covered by any epic)"],
  "total_estimated_sprints": 0
}"""

    @classmethod
    def get_generation_template(cls) -> ChatPromptTemplate:
        """Build epic generation prompt template."""
        return ChatPromptTemplate.from_messages([
            ("system", cls.SYSTEM),
            ("human", """## Structured Requirements
{requirements_json}

## Project Context
Project Name: {project_name}
Team Size: {team_size}
Sprint Length: {sprint_length_weeks} weeks
Domain: {domain}
Target Users: {target_users}

{rag_context}

## Instructions
1. Analyze the requirements and group them into coherent epics
2. Each epic should deliver end-to-end business value
3. Avoid epics that are purely technical (unless explicitly required)
4. Ensure every requirement is covered by at least one epic
5. Order epics by priority and dependencies (which epics must come first)
6. Note any requirements that don't fit into any epic as coverage gaps
7. Provide realistic story point ranges based on the team size
8. Respond ONLY with valid JSON matching the schema above"""),
        ])
