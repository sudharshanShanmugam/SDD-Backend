"""
User Story Generation Prompts
"""

from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts.system_prompts import SystemPrompts


class StoryPrompts:
    """Prompts for user story generation."""

    SYSTEM = SystemPrompts.PRODUCT_OWNER + """

## Story Writing Guidelines
- Follow the standard format: "As a [persona], I want [goal] so that [benefit]"
- Apply INVEST criteria strictly:
  * Independent: Stories should be deliverable independently
  * Negotiable: Details can be discussed/changed
  * Valuable: Each story delivers user or business value
  * Estimable: Team can estimate with reasonable confidence
  * Small: Completable within a single sprint
  * Testable: Clear acceptance criteria in Gherkin format

## Story Point Scale (Fibonacci)
1 - Trivial change (< 2 hours)
2 - Simple task (half day)
3 - Small feature (1 day)
5 - Medium feature (2-3 days)
8 - Complex feature (1 week)
13 - Very complex (needs breaking down)
21 - Epic-level (must be split)

## Output Schema
{
  "stories": [
    {
      "id": "US-XXX",
      "epic_id": "EPIC-XXX",
      "title": "string",
      "user_story": "As a [persona], I want [goal] so that [benefit]",
      "persona": "string",
      "goal": "string",
      "benefit": "string",
      "acceptance_criteria": [
        {
          "id": "AC-XXX",
          "scenario": "string",
          "given": "string",
          "when": "string",
          "then": "string"
        }
      ],
      "story_points": 0,
      "priority": "critical|high|medium|low",
      "labels": ["string"],
      "dependencies": ["US-XXX"],
      "blocked_by": ["US-XXX"],
      "requirement_ids": ["FR-XXX"],
      "notes": "string",
      "definition_of_done": ["string"],
      "out_of_scope": ["string"]
    }
  ],
  "invest_analysis": {
    "issues": [
      {
        "story_id": "US-XXX",
        "criterion": "string",
        "issue": "string",
        "suggestion": "string"
      }
    ]
  }
}"""

    @classmethod
    def get_generation_template(cls) -> ChatPromptTemplate:
        """Build story generation prompt template."""
        return ChatPromptTemplate.from_messages([
            ("system", cls.SYSTEM),
            ("human", """## Epic Details
{epic_json}

## Related Requirements
{requirements_json}

## Existing Stories in Project (for context/deduplication)
{existing_stories_json}

## Team Context
Personas: {personas_json}
Sprint Velocity: {sprint_velocity} points
Sprint Length: {sprint_length_weeks} weeks

{rag_context}

## Instructions
1. Generate user stories that collectively implement the epic's acceptance criteria
2. Each story must pass the INVEST test
3. Write acceptance criteria in strict Gherkin format (Given/When/Then)
4. Stories with > 8 points should be flagged or split
5. Identify story dependencies and ordering
6. Map stories back to their source requirements
7. Specify what is explicitly OUT OF SCOPE for each story
8. Respond ONLY with valid JSON"""),
        ])
