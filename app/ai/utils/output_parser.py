"""
Structured Output Parser Module

Robust parsers for converting LLM outputs to validated Pydantic models.
Handles JSON extraction, repair, and validation with detailed error reporting.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import BaseOutputParser
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _attempt_json_repair(malformed_json: str) -> Optional[str]:
    """
    Attempt to repair common JSON formatting issues from LLMs.
    Returns repaired JSON string or None if repair fails.
    """
    text = malformed_json.strip()

    # Remove trailing commas before ] or }
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Fix unquoted keys
    text = re.sub(r"(?<=[{,])\s*(\w+)\s*:", r'"\1":', text)

    # Fix single quotes used instead of double quotes
    # (careful with apostrophes in values)
    text = re.sub(r"(?<!\\)'", '"', text)

    # Remove JavaScript-style comments
    text = re.sub(r"//[^\n]*\n", "\n", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # Ensure the string ends properly
    if text and text[-1] not in ("}", "]", '"'):
        # Try to close open structures
        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")
        text += "}" * max(0, open_braces) + "]" * max(0, open_brackets)

    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        return None


def extract_json_block(text: str) -> Optional[str]:
    """
    Extract JSON from a text that may contain markdown code blocks,
    explanatory text, or other non-JSON content.
    """
    # Strategy 1: markdown code block with json tag
    match = re.search(r"```json\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Strategy 2: any markdown code block
    match = re.search(r"```\s*([\s\S]+?)\s*```", text)
    if match:
        candidate = match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Strategy 3: find largest JSON object in text
    # Look for outermost { ... } or [ ... ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue

        # Walk backwards from end to find matching close
        depth = 0
        in_string = False
        escape_next = False
        end_idx = -1

        for i, char in enumerate(text[start_idx:], start_idx):
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == start_char:
                depth += 1
            elif char == end_char:
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break

        if end_idx != -1:
            candidate = text[start_idx : end_idx + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                repaired = _attempt_json_repair(candidate)
                if repaired:
                    return repaired

    return None


class StructuredOutputParser(BaseOutputParser[T], Generic[T]):
    """
    Production-grade structured output parser for Pydantic models.

    Features:
    - JSON extraction from markdown-wrapped responses
    - JSON repair for common LLM formatting issues
    - Pydantic validation with detailed error messages
    - Automatic retry instructions on parse failure
    """

    pydantic_class: Type[T]

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, pydantic_class: Type[T], **kwargs):
        super().__init__(pydantic_class=pydantic_class, **kwargs)

    def parse(self, text: str) -> T:
        """Parse LLM output text into a validated Pydantic model."""
        # Step 1: Extract JSON block
        json_str = extract_json_block(text)

        if not json_str:
            raise OutputParserException(
                f"Failed to extract JSON from response. "
                f"Response started with: {text[:200]!r}",
                llm_output=text,
            )

        # Step 2: Parse JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            # Attempt repair
            repaired = _attempt_json_repair(json_str)
            if repaired:
                try:
                    data = json.loads(repaired)
                    logger.debug("JSON repaired successfully")
                except json.JSONDecodeError:
                    raise OutputParserException(
                        f"Failed to parse JSON (even after repair): {e}",
                        llm_output=text,
                    ) from e
            else:
                raise OutputParserException(
                    f"Invalid JSON in LLM response: {e}",
                    llm_output=text,
                ) from e

        # Step 3: Validate with Pydantic
        try:
            return self.pydantic_class.model_validate(data)
        except ValidationError as e:
            raise OutputParserException(
                f"Output failed schema validation: {e}",
                llm_output=text,
            ) from e

    def get_format_instructions(self) -> str:
        """Return format instructions to include in the prompt."""
        schema = self.pydantic_class.model_json_schema()
        return (
            f"Respond with a JSON object matching this schema:\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```\n"
            "Do not include any text outside the JSON object."
        )

    @property
    def _type(self) -> str:
        return "structured_output_parser"


def parse_json_safely(
    text: str,
    schema: Optional[Type[T]] = None,
    default: Any = None,
) -> Any:
    """
    Parse JSON from text with optional schema validation.
    Returns default value on failure instead of raising.
    """
    try:
        json_str = extract_json_block(text) or text
        data = json.loads(json_str)

        if schema:
            return schema.model_validate(data)
        return data

    except (json.JSONDecodeError, ValidationError, Exception) as e:
        logger.warning("JSON parse failed: %s. Text: %r", e, text[:200])
        return default


def merge_partial_outputs(outputs: List[Dict]) -> Dict:
    """
    Merge multiple partial JSON outputs from chunked processing.
    Combines list fields and merges dict fields.
    """
    if not outputs:
        return {}

    merged = {}
    for output in outputs:
        for key, value in output.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(value, list) and isinstance(merged[key], list):
                merged[key].extend(value)
            elif isinstance(value, dict) and isinstance(merged[key], dict):
                merged[key].update(value)
            else:
                # Keep the last value for scalar fields
                merged[key] = value

    return merged
