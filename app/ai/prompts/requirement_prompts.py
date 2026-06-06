"""
Requirement Extraction and Structuring Prompts
"""

from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate

from app.ai.prompts.system_prompts import SystemPrompts


REQUIREMENT_EXTRACTION_EXAMPLES = [
    {
        "input": "The system should allow users to log in using their email and password. "
                 "It must support SSO with Google and Microsoft. The login page should load "
                 "within 2 seconds. User data must be encrypted at rest.",
        "output": """{
  "functional_requirements": [
    {
      "id": "FR-001",
      "title": "Email/Password Authentication",
      "description": "Users shall be able to authenticate using their registered email address and password",
      "category": "authentication",
      "priority": "must_have",
      "source_text": "allow users to log in using their email and password",
      "ambiguity_flag": false,
      "clarification_needed": null
    },
    {
      "id": "FR-002",
      "title": "SSO Integration - Google",
      "description": "The system shall support Single Sign-On authentication via Google OAuth 2.0",
      "category": "authentication",
      "priority": "must_have",
      "source_text": "support SSO with Google",
      "ambiguity_flag": false,
      "clarification_needed": null
    },
    {
      "id": "FR-003",
      "title": "SSO Integration - Microsoft",
      "description": "The system shall support Single Sign-On authentication via Microsoft Azure AD",
      "category": "authentication",
      "priority": "must_have",
      "source_text": "support SSO with Microsoft",
      "ambiguity_flag": false,
      "clarification_needed": null
    }
  ],
  "non_functional_requirements": [
    {
      "id": "NFR-001",
      "title": "Login Page Performance",
      "description": "The login page shall render and become interactive within 2 seconds under normal load conditions",
      "category": "performance",
      "priority": "must_have",
      "metric": "< 2 seconds page load time",
      "source_text": "login page should load within 2 seconds"
    },
    {
      "id": "NFR-002",
      "title": "Data Encryption at Rest",
      "description": "All user data stored in the database shall be encrypted at rest using AES-256 or equivalent",
      "category": "security",
      "priority": "must_have",
      "metric": "AES-256 encryption",
      "source_text": "User data must be encrypted at rest"
    }
  ],
  "constraints": [],
  "assumptions": [
    {
      "id": "ASM-001",
      "description": "Users will have access to a modern browser supporting OAuth 2.0 flows",
      "impact": "SSO features require modern browser compatibility"
    }
  ],
  "dependencies": [],
  "ambiguous_items": []
}""",
    }
]


class RequirementPrompts:
    """Prompts for requirement extraction and structuring."""

    EXTRACTION_SYSTEM = SystemPrompts.REQUIREMENT_ANALYST + """

## Output Schema
You MUST respond with valid JSON matching this exact structure:
{
  "functional_requirements": [
    {
      "id": "FR-XXX",
      "title": "string (concise, action-oriented)",
      "description": "string (detailed, unambiguous)",
      "category": "string (auth|data|ui|integration|business_logic|reporting|admin)",
      "priority": "string (must_have|should_have|could_have|wont_have)",
      "source_text": "string (exact quote from source document)",
      "ambiguity_flag": boolean,
      "clarification_needed": "string | null"
    }
  ],
  "non_functional_requirements": [
    {
      "id": "NFR-XXX",
      "title": "string",
      "description": "string",
      "category": "string (performance|security|scalability|reliability|usability|maintainability|compliance)",
      "priority": "string (must_have|should_have|could_have)",
      "metric": "string (measurable acceptance criterion)",
      "source_text": "string"
    }
  ],
  "constraints": [
    {
      "id": "CON-XXX",
      "title": "string",
      "description": "string",
      "type": "string (technical|business|regulatory|time|budget)",
      "impact": "string"
    }
  ],
  "assumptions": [
    {
      "id": "ASM-XXX",
      "description": "string",
      "impact": "string",
      "validation_needed": boolean
    }
  ],
  "dependencies": [
    {
      "id": "DEP-XXX",
      "description": "string",
      "type": "string (internal|external|technical|business)",
      "affects": ["FR-XXX", "NFR-XXX"]
    }
  ],
  "ambiguous_items": [
    {
      "id": "AMB-XXX",
      "source_text": "string",
      "reason": "string",
      "clarification_questions": ["string"]
    }
  ]
}"""

    @classmethod
    def get_extraction_template(cls) -> ChatPromptTemplate:
        """Build the few-shot extraction prompt template."""
        example_prompt = ChatPromptTemplate.from_messages([
            ("human", "{input}"),
            ("ai", "{output}"),
        ])

        few_shot_prompt = FewShotChatMessagePromptTemplate(
            example_prompt=example_prompt,
            examples=REQUIREMENT_EXTRACTION_EXAMPLES,
        )

        return ChatPromptTemplate.from_messages([
            ("system", cls.EXTRACTION_SYSTEM),
            few_shot_prompt,
            ("human", """## Document Content to Analyze

{document_content}

## Additional Context
Project Type: {project_type}
Domain: {domain}
Stakeholder Notes: {stakeholder_notes}

{rag_context}

## Instructions
1. Extract ALL requirements from the document above
2. Assign sequential IDs (FR-001, FR-002, etc.)
3. Flag ANY ambiguous statements with clarification questions
4. Do NOT invent requirements not present in the document
5. Preserve exact source text for traceability
6. Respond ONLY with valid JSON, no explanations"""),
        ])

    STRUCTURING_SYSTEM = SystemPrompts.REQUIREMENT_ANALYST + """

You are given raw extracted requirements and must structure them by:
1. Grouping related requirements into logical domains
2. Resolving conflicts between requirements
3. Identifying missing requirements based on implied functionality
4. Assigning business value scores (1-10)
5. Creating a dependency graph

Respond with valid JSON only."""

    @classmethod
    def get_structuring_template(cls) -> ChatPromptTemplate:
        """Build the structuring prompt template."""
        return ChatPromptTemplate.from_messages([
            ("system", cls.STRUCTURING_SYSTEM),
            ("human", """## Raw Requirements
{raw_requirements_json}

## Existing Requirements in System (for deduplication)
{existing_requirements_json}

{rag_context}

## Task
1. Group requirements into logical domains/modules
2. Detect and flag conflicting requirements
3. Identify implied requirements that are missing
4. Score each requirement for business value (1-10) and technical complexity (1-10)
5. Build dependency relationships between requirements
6. Respond with the structured JSON schema below:

{{
  "domains": [
    {{
      "name": "string",
      "description": "string",
      "requirements": ["FR-001", "FR-002"],
      "priority_order": ["FR-001", "FR-002"]
    }}
  ],
  "structured_requirements": [
    {{
      "id": "string",
      "title": "string",
      "description": "string",
      "type": "functional|non_functional|constraint|assumption",
      "category": "string",
      "priority": "must_have|should_have|could_have|wont_have",
      "business_value": 0,
      "technical_complexity": 0,
      "dependencies": ["FR-XXX"],
      "conflicts_with": ["FR-XXX"],
      "implied_by": ["FR-XXX"],
      "domain": "string",
      "tags": ["string"],
      "acceptance_criteria": ["string"]
    }}
  ],
  "conflicts": [
    {{
      "requirement_ids": ["FR-XXX", "FR-YYY"],
      "conflict_description": "string",
      "resolution_suggestion": "string"
    }}
  ],
  "missing_requirements": [
    {{
      "suggested_title": "string",
      "reason": "string",
      "implied_by": ["FR-XXX"],
      "priority": "string"
    }}
  ],
  "summary": {{
    "total_functional": 0,
    "total_non_functional": 0,
    "total_constraints": 0,
    "must_have_count": 0,
    "conflict_count": 0,
    "ambiguity_count": 0
  }}
}}"""),
        ])
