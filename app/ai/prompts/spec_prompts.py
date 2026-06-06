"""
UI/UX and API Specification Prompts
"""

from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts.system_prompts import SystemPrompts


class SpecPrompts:
    """Prompts for UI/UX and API specification generation."""

    UI_SYSTEM = SystemPrompts.SOFTWARE_ARCHITECT + """

## UI Specification Guidelines
- Describe components at the implementation level (not wireframe level)
- Include: layout, component hierarchy, state management, interactions
- Follow atomic design: atoms → molecules → organisms → templates → pages
- Include responsive breakpoints (mobile, tablet, desktop)
- Specify accessibility attributes (aria-label, role, tabindex)
- Define loading, error, and empty states for all data-driven components

## Output Schema
{
  "ui_spec": {
    "page_name": "string",
    "route": "string",
    "description": "string",
    "layout": {
      "type": "string (full-width|centered|sidebar|split)",
      "max_width": "string",
      "responsive_breakpoints": {
        "mobile": "< 768px",
        "tablet": "768px - 1024px",
        "desktop": "> 1024px"
      }
    },
    "components": [
      {
        "id": "string",
        "name": "string",
        "type": "string (page|section|form|table|modal|card|...)",
        "description": "string",
        "props": [
          {
            "name": "string",
            "type": "string (TypeScript type)",
            "required": true,
            "default": "any",
            "description": "string"
          }
        ],
        "state": [
          {
            "name": "string",
            "type": "string",
            "initial_value": "any",
            "description": "string"
          }
        ],
        "interactions": [
          {
            "trigger": "string (click|hover|focus|submit|...)",
            "action": "string",
            "outcome": "string"
          }
        ],
        "accessibility": {
          "role": "string",
          "aria_label": "string",
          "keyboard_navigation": ["string"],
          "wcag_level": "A|AA|AAA"
        },
        "loading_state": "string",
        "error_state": "string",
        "empty_state": "string",
        "children": []
      }
    ],
    "data_flows": [
      {
        "trigger": "string",
        "api_calls": ["string"],
        "state_updates": ["string"],
        "ui_updates": ["string"]
      }
    ],
    "validation_rules": [
      {
        "field": "string",
        "rules": ["string"],
        "error_messages": {"rule": "message"}
      }
    ]
  }
}"""

    API_SYSTEM = SystemPrompts.SOFTWARE_ARCHITECT + """

## API Specification Guidelines
- Follow OpenAPI 3.0.3 specification exactly
- RESTful design: proper HTTP verbs, status codes, resource naming
- Include authentication: Bearer JWT in all protected endpoints
- Paginate all list endpoints using cursor-based pagination
- Include request/response examples for all endpoints
- Define reusable schemas in the components section
- Use semantic versioning in the API path (/api/v1/...)

Respond with a complete, valid OpenAPI 3.0 JSON document."""

    @classmethod
    def get_ui_spec_template(cls) -> ChatPromptTemplate:
        """Build UI specification prompt template."""
        return ChatPromptTemplate.from_messages([
            ("system", cls.UI_SYSTEM),
            ("human", """## Epic / Stories
{stories_json}

## Design System
Component Library: {component_library}
Design Tokens: {design_tokens_json}
Existing Components: {existing_components_json}

## User Personas
{personas_json}

{rag_context}

## Instructions
1. Design the UI specification for the described feature set
2. List all pages/views needed
3. For each page, define the complete component hierarchy
4. Include all user interactions and state transitions
5. Define API integrations for each component
6. Ensure WCAG 2.1 AA compliance in all components
7. Respond ONLY with valid JSON"""),
        ])

    @classmethod
    def get_api_spec_template(cls) -> ChatPromptTemplate:
        """Build API specification prompt template."""
        return ChatPromptTemplate.from_messages([
            ("system", cls.API_SYSTEM),
            ("human", """## Epic / Stories
{stories_json}

## Data Models
{data_models_json}

## Authentication Method
{auth_method}

## Existing API Endpoints (for consistency)
{existing_endpoints_json}

## API Standards
Base URL: {base_url}
API Version: {api_version}
Auth: Bearer JWT

{rag_context}

## Instructions
1. Generate a COMPLETE OpenAPI 3.0.3 JSON specification
2. Include ALL endpoints needed to implement the stories
3. Define comprehensive request/response schemas
4. Include proper HTTP status codes and error responses
5. Add request validation constraints (minLength, maxLength, pattern, etc.)
6. Include pagination for all collection endpoints
7. Add security schemes (BearerAuth)
8. Include realistic examples for all schemas
9. Follow REST naming conventions (/resources/{id}/sub-resources)
10. Respond ONLY with the raw OpenAPI JSON document"""),
        ])
