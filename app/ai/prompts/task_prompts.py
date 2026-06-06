"""
Task Breakdown Prompts
"""

from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts.system_prompts import SystemPrompts


class TaskPrompts:
    """Prompts for engineering task breakdown."""

    SYSTEM = SystemPrompts.TECH_LEAD + """

## Task Breakdown Guidelines
- Break each story into concrete engineering tasks (2-8 hours each)
- Cover: Backend, Frontend, Database, Tests, Documentation
- Each task should be assignable to a single engineer
- Include specific technical details (file names, API endpoints, DB tables)
- Separate concerns: don't mix frontend and backend in the same task
- Always include a testing task for each implementation task

## Task Categories
- BACKEND: Server-side logic, APIs, services, business logic
- FRONTEND: UI components, pages, state management
- DATABASE: Schema changes, migrations, indexes, queries
- DEVOPS: Infrastructure, CI/CD, deployment configs
- TESTING: Unit tests, integration tests, E2E tests
- DOCUMENTATION: API docs, code comments, ADRs

## Output Schema
{
  "tasks": [
    {
      "id": "TASK-XXX",
      "story_id": "US-XXX",
      "title": "string (specific, technical)",
      "description": "string (detailed implementation guidance)",
      "category": "BACKEND|FRONTEND|DATABASE|DEVOPS|TESTING|DOCUMENTATION",
      "estimated_hours": 0,
      "complexity": "trivial|simple|medium|complex",
      "technical_details": {
        "files_to_modify": ["string"],
        "new_files": ["string"],
        "api_endpoints": ["string"],
        "database_changes": ["string"],
        "dependencies": ["string (npm/pip packages)"],
        "environment_variables": ["string"]
      },
      "acceptance_criteria": ["string"],
      "dependencies": ["TASK-XXX"],
      "assignee_role": "backend_engineer|frontend_engineer|fullstack|devops|qa",
      "labels": ["string"],
      "subtasks": [
        {
          "title": "string",
          "estimated_hours": 0
        }
      ]
    }
  ],
  "summary": {
    "total_tasks": 0,
    "total_hours": 0,
    "by_category": {
      "BACKEND": 0,
      "FRONTEND": 0,
      "DATABASE": 0,
      "DEVOPS": 0,
      "TESTING": 0,
      "DOCUMENTATION": 0
    }
  }
}"""

    @classmethod
    def get_breakdown_template(cls) -> ChatPromptTemplate:
        """Build task breakdown prompt template."""
        return ChatPromptTemplate.from_messages([
            ("system", cls.SYSTEM),
            ("human", """## User Story
{story_json}

## Technical Context
Tech Stack: {tech_stack_json}
Architecture: {architecture}
Database: {database_type}
Frontend Framework: {frontend_framework}

## Existing Codebase Context
{codebase_context}

{rag_context}

## Instructions
1. Break the story into concrete, time-bounded engineering tasks
2. Be specific about what needs to be built (file names, endpoints, components)
3. Include a task for writing tests (aim for 80%+ coverage)
4. Include a task for updating documentation
5. Order tasks by dependency (what must be done first)
6. Each task should take 2-8 hours; split anything larger
7. Respond ONLY with valid JSON"""),
        ])
