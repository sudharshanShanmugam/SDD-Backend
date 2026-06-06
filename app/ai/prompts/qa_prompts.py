"""
QA Test Generation Prompts
"""

from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts.system_prompts import SystemPrompts


class QAPrompts:
    """Prompts for QA test case generation."""

    SYSTEM = SystemPrompts.QA_ENGINEER + """

## Test Case Design Principles
- Cover: Happy path, Edge cases, Negative cases, Boundary values, Security tests
- Write tests at the right level: Unit (70%), Integration (20%), E2E (10%)
- Accessibility: Include WCAG 2.1 AA tests for all UI stories
- Performance: Include load/performance tests for critical paths
- Security: Include auth/authz tests, input validation, XSS, SQL injection

## Output Schema
{
  "test_suite": {
    "story_id": "US-XXX",
    "test_cases": [
      {
        "id": "TC-XXX",
        "title": "string",
        "type": "functional|edge_case|negative|accessibility|performance|security",
        "priority": "critical|high|medium|low",
        "preconditions": ["string"],
        "test_steps": [
          {
            "step_number": 1,
            "action": "string",
            "expected_result": "string"
          }
        ],
        "expected_result": "string",
        "test_data": {"key": "value"},
        "tags": ["string"],
        "automation_feasible": true
      }
    ],
    "playwright_code": "string (complete TypeScript test file)",
    "cypress_code": "string (complete JavaScript test file)",
    "coverage_analysis": {
      "acceptance_criteria_covered": ["AC-XXX"],
      "coverage_percent": 0,
      "gaps": ["string"]
    }
  }
}"""

    PLAYWRIGHT_TEMPLATE = """
import {{ test, expect }} from '@playwright/test';

test.describe('{story_title}', () => {{
  test.beforeEach(async ({{ page }}) => {{
    // Setup
  }});

  {test_cases}
}});
"""

    CYPRESS_TEMPLATE = """
describe('{story_title}', () => {{
  beforeEach(() => {{
    // Setup
  }});

  {test_cases}
}});
"""

    @classmethod
    def get_generation_template(cls) -> ChatPromptTemplate:
        """Build QA generation prompt template."""
        return ChatPromptTemplate.from_messages([
            ("system", cls.SYSTEM),
            ("human", """## User Story
{story_json}

## Acceptance Criteria
{acceptance_criteria_json}

## UI Specifications (if available)
{ui_spec_json}

## API Specifications (if available)
{api_spec_json}

## Tech Stack
Frontend: {frontend_framework}
E2E Framework: {e2e_framework}

{rag_context}

## Instructions
1. Generate test cases covering ALL acceptance criteria
2. Include at least 3 negative test cases
3. Include edge cases for all input fields (empty, max length, special chars)
4. Write complete, runnable Playwright TypeScript test code
5. Write complete, runnable Cypress JavaScript test code
6. Include accessibility tests using axe-core assertions
7. Mark security-sensitive tests appropriately
8. Calculate coverage percentage against acceptance criteria
9. Respond ONLY with valid JSON

## Important for Code Generation
- Use async/await in Playwright tests
- Use proper Playwright locators (getByRole, getByLabel, getByTestId)
- Use cy.get with data-testid attributes in Cypress
- Include proper assertions, not just clicks
- Handle loading states and async operations"""),
        ])
