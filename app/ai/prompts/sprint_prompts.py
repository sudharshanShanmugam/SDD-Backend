"""
Sprint Planning Prompts
"""

from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts.system_prompts import SystemPrompts


class SprintPrompts:
    """Prompts for sprint planning."""

    SYSTEM = SystemPrompts.SCRUM_MASTER + """

## Sprint Planning Rules
1. Never exceed team velocity by more than 10%
2. Include at least 10% capacity for bug fixes and tech debt
3. Respect story dependencies (prerequisites must be in earlier sprints)
4. Balance frontend, backend, and QA work in each sprint
5. Include sprint goals that are testable and meaningful to stakeholders
6. Flag risks and dependencies that could derail the sprint

## Output Schema
Respond ONLY with valid JSON matching this exact structure (double-braces are literal braces):
{{
  "sprint_plan": {{
    "total_sprints": 0,
    "release_date": "YYYY-MM-DD",
    "sprints": [
      {{
        "sprint_number": 1,
        "sprint_name": "string",
        "goal": "string",
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD",
        "capacity_points": 0,
        "committed_points": 0,
        "stories": [
          {{
            "story_id": "identifier from input (e.g. US-001)",
            "story_title": "string",
            "story_points": 0,
            "rationale": "string (why in this sprint)"
          }}
        ],
        "milestones": ["string"],
        "risks": [
          {{
            "description": "string",
            "probability": "low|medium|high",
            "impact": "low|medium|high",
            "mitigation": "string"
          }}
        ],
        "dependencies": [],
        "tech_debt_items": ["string"]
      }}
    ],
    "unplanned_stories": [
      {{
        "story_id": "US-XXX",
        "reason": "string"
      }}
    ],
    "capacity_analysis": {{
      "total_available_points": 0,
      "total_committed_points": 0,
      "utilization_percent": 0,
      "buffer_points": 0
    }},
    "release_milestones": []
  }}
}}"""

    @classmethod
    def get_planning_template(cls) -> ChatPromptTemplate:
        """Build sprint planning prompt template."""
        return ChatPromptTemplate.from_messages([
            ("system", cls.SYSTEM),
            ("human", """## User Stories to Plan
{stories_json}

## Team Configuration
Team Size: {team_size} developers
Sprint Length: {sprint_length_weeks} weeks
Sprint Velocity: {sprint_velocity} story points
Number of Sprints: {num_sprints}
Project Start Date: {start_date}

## Capacity Breakdown
{capacity_breakdown_json}

## Constraints
{constraints_json}

{rag_context}

## Instructions
1. Create a sprint plan covering all {num_sprints} sprints
2. Respect all story dependencies (don't schedule a story before its dependencies)
3. Never exceed {sprint_velocity} points per sprint
4. Reserve 10% capacity for unexpected work and bugs
5. Create a meaningful sprint goal for each sprint
6. Group stories that deliver a coherent feature set in the same sprint
7. Identify any stories that cannot be planned (explain why)
8. Respond ONLY with valid JSON"""),
        ])
