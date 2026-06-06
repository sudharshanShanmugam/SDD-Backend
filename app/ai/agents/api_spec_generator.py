"""
API Specification Generator Agent

Generates complete, valid OpenAPI 3.0 specifications from epics and user stories.
Includes paths, schemas, security definitions, examples, and error responses.
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


class OpenAPISpec(BaseModel):
    """Container for a complete OpenAPI specification."""
    spec: Dict[str, Any] = Field(default_factory=dict)
    raw_json: str = ""
    endpoint_count: int = 0
    schema_count: int = 0
    validation_errors: List[str] = Field(default_factory=list)


class APISpecGeneratorAgent(BaseAgent[OpenAPISpec]):
    """
    Generates complete OpenAPI 3.0.3 specifications.

    Input:
        - Epic and associated user stories
        - Existing data models
        - Authentication method
        - Existing API endpoints (for consistency)

    Output:
        OpenAPISpec with:
        - Complete OpenAPI 3.0.3 JSON document
        - All CRUD endpoints for resources
        - Comprehensive request/response schemas
        - JWT Bearer security scheme
        - Cursor-based pagination on all list endpoints
        - Error response schemas (400, 401, 403, 404, 422, 500)
        - Realistic examples for all schemas
    """

    def __init__(self):
        super().__init__(
            task_name="api_spec_generation",
            output_schema=OpenAPISpec,
            enable_rag=True,
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        return SpecPrompts.get_api_spec_template()

    async def _parse_output(self, raw_output: str) -> OpenAPISpec:
        """Parse output as OpenAPI JSON spec."""
        json_str = self._extract_json_from_response(raw_output)
        try:
            spec_data = json.loads(json_str)

            # Validate it looks like an OpenAPI spec
            if "openapi" not in spec_data and "swagger" not in spec_data:
                logger.warning("Output may not be a valid OpenAPI spec - missing 'openapi' key")

            endpoint_count = len(spec_data.get("paths", {}))
            schema_count = len(
                spec_data.get("components", {}).get("schemas", {})
            )

            # Validate required OpenAPI fields
            validation_errors = []
            for required_field in ["info", "paths"]:
                if required_field not in spec_data:
                    validation_errors.append(f"Missing required field: {required_field}")

            info = spec_data.get("info", {})
            for info_field in ["title", "version"]:
                if info_field not in info:
                    validation_errors.append(f"Missing info.{info_field}")

            return OpenAPISpec(
                spec=spec_data,
                raw_json=json.dumps(spec_data, indent=2),
                endpoint_count=endpoint_count,
                schema_count=schema_count,
                validation_errors=validation_errors,
            )
        except Exception as e:
            logger.error("Failed to parse API spec output: %s", e)
            return OpenAPISpec(
                validation_errors=[f"Parse error: {str(e)}"]
            )

    async def generate(
        self,
        stories: List[Dict[str, Any]],
        data_models: Optional[List[Dict]] = None,
        auth_method: str = "Bearer JWT",
        existing_endpoints: Optional[List[Dict]] = None,
        base_url: str = "https://api.example.com",
        api_version: str = "v1",
        rag_results: Optional[List[Dict]] = None,
        organization_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Generate OpenAPI specification for the given stories.

        Args:
            stories: List of user stories that define the API behavior
            data_models: Existing data model definitions
            auth_method: Authentication method description
            existing_endpoints: Existing API endpoints for consistency
            base_url: API base URL
            api_version: API version string
            rag_results: Similar past API specs for reference
            organization_id: Organization ID

        Returns:
            AgentResult with OpenAPISpec
        """
        input_data = {
            "stories_json": json.dumps(stories, indent=2),
            "data_models_json": json.dumps(data_models or [], indent=2),
            "auth_method": auth_method,
            "existing_endpoints_json": json.dumps(existing_endpoints or [], indent=2),
            "base_url": base_url,
            "api_version": api_version,
        }

        result = await self.run(
            input_data=input_data,
            rag_results=rag_results,
            organization_id=organization_id,
        )

        if result.success and result.data:
            spec: OpenAPISpec = result.data
            logger.info(
                "Generated API spec: %d endpoints, %d schemas, %d validation errors",
                spec.endpoint_count,
                spec.schema_count,
                len(spec.validation_errors),
            )
            if spec.validation_errors:
                logger.warning("API spec validation errors: %s", spec.validation_errors)

        return result

    def _ensure_security_scheme(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure the spec has proper security schemes."""
        if "components" not in spec:
            spec["components"] = {}

        if "securitySchemes" not in spec["components"]:
            spec["components"]["securitySchemes"] = {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "JWT access token. Include in Authorization header as: Bearer <token>",
                }
            }

        # Add global security if not present
        if "security" not in spec:
            spec["security"] = [{"BearerAuth": []}]

        return spec

    def _add_standard_error_responses(
        self, spec: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Add standard error response schemas to components."""
        if "components" not in spec:
            spec["components"] = {}

        if "schemas" not in spec["components"]:
            spec["components"]["schemas"] = {}

        spec["components"]["schemas"]["ErrorResponse"] = {
            "type": "object",
            "required": ["error", "message"],
            "properties": {
                "error": {
                    "type": "string",
                    "example": "VALIDATION_ERROR",
                },
                "message": {
                    "type": "string",
                    "example": "The request body contains invalid data",
                },
                "details": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "message": {"type": "string"},
                        },
                    },
                },
                "trace_id": {
                    "type": "string",
                    "format": "uuid",
                    "example": "550e8400-e29b-41d4-a716-446655440000",
                },
            },
        }

        spec["components"]["schemas"]["PaginatedResponse"] = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "items": {},
                },
                "pagination": {
                    "type": "object",
                    "properties": {
                        "cursor": {"type": "string", "nullable": True},
                        "has_more": {"type": "boolean"},
                        "total_count": {"type": "integer"},
                        "page_size": {"type": "integer"},
                    },
                },
            },
        }

        return spec
