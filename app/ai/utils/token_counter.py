"""
Token Counter Module

Accurate token counting and budget management for OpenAI models.
Uses tiktoken for exact token counts matching the API billing.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# Model token limits
MODEL_TOKEN_LIMITS: Dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    "text-embedding-3-large": 8191,
    "text-embedding-3-small": 8191,
}

# Max output tokens per model
MODEL_MAX_OUTPUT_TOKENS: Dict[str, int] = {
    "gpt-4o": 16384,
    "gpt-4o-mini": 16384,
    "gpt-4-turbo": 4096,
    "gpt-4": 4096,
    "gpt-3.5-turbo": 4096,
}

# Cost per 1K tokens (USD) - input/output
MODEL_COSTS: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.010, "output": 0.030},
    "text-embedding-3-large": {"input": 0.00013, "output": 0.0},
    "text-embedding-3-small": {"input": 0.00002, "output": 0.0},
}


@lru_cache(maxsize=4)
def _get_encoding(model_name: str):
    """Get tiktoken encoding for a model (cached)."""
    try:
        import tiktoken
        # Map model names to encoding names
        encoding_map = {
            "gpt-4o": "o200k_base",
            "gpt-4o-mini": "o200k_base",
        }
        encoding_name = encoding_map.get(model_name, "cl100k_base")
        return tiktoken.get_encoding(encoding_name)
    except ImportError:
        logger.warning("tiktoken not installed; using approximate token counting")
        return None
    except Exception as e:
        logger.warning("Failed to load tiktoken encoding: %s", e)
        return None


class TokenCounter:
    """
    Accurate token counter using tiktoken.

    Provides:
    - Exact token counts for OpenAI models
    - Prompt budget management
    - Cost estimation
    - Context window fitting
    """

    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name
        self.max_tokens = MODEL_TOKEN_LIMITS.get(model_name, 128000)
        self.max_output_tokens = MODEL_MAX_OUTPUT_TOKENS.get(model_name, 4096)
        self._encoding = _get_encoding(model_name)

    def count_tokens(self, text: str) -> int:
        """Count tokens in a string."""
        if not text:
            return 0

        if self._encoding:
            return len(self._encoding.encode(text))

        # Fallback: approximate using word count * 1.3
        return int(len(text.split()) * 1.3)

    def count_messages_tokens(self, messages: List[Dict]) -> int:
        """
        Count tokens for a list of chat messages.
        Includes per-message overhead as per OpenAI tokenization.
        """
        total = 0
        # Per-message overhead (role + separators)
        overhead_per_message = 4

        for message in messages:
            total += overhead_per_message
            for key, value in message.items():
                if isinstance(value, str):
                    total += self.count_tokens(value)
                elif isinstance(value, list):
                    # Handle content arrays (multimodal)
                    for item in value:
                        if isinstance(item, dict) and "text" in item:
                            total += self.count_tokens(item["text"])

        total += 3  # Reply priming tokens
        return total

    def fits_in_context(
        self,
        text: str,
        reserved_output_tokens: int = 4096,
    ) -> bool:
        """Check if text fits in the model's context window."""
        token_count = self.count_tokens(text)
        available = self.max_tokens - reserved_output_tokens
        return token_count <= available

    def truncate_to_fit(
        self,
        text: str,
        max_tokens: int,
        truncation_suffix: str = "\n...[truncated]",
    ) -> str:
        """Truncate text to fit within token budget."""
        if self.count_tokens(text) <= max_tokens:
            return text

        if self._encoding:
            suffix_tokens = self.count_tokens(truncation_suffix)
            target_tokens = max_tokens - suffix_tokens

            tokens = self._encoding.encode(text)
            truncated_tokens = tokens[:target_tokens]
            return self._encoding.decode(truncated_tokens) + truncation_suffix

        # Fallback: character-based truncation (rough)
        chars_per_token = 4
        target_chars = (max_tokens - self.count_tokens(truncation_suffix)) * chars_per_token
        return text[:target_chars] + truncation_suffix

    def split_into_chunks(
        self,
        text: str,
        chunk_size: int,
        overlap_tokens: int = 50,
    ) -> List[str]:
        """Split text into chunks that fit within token limits."""
        if not self._encoding:
            # Fallback: split by approximate character count
            chars_per_token = 4
            chunk_chars = chunk_size * chars_per_token
            overlap_chars = overlap_tokens * chars_per_token
            chunks = []
            start = 0
            while start < len(text):
                end = min(start + chunk_chars, len(text))
                chunks.append(text[start:end])
                start = end - overlap_chars
                if start >= len(text):
                    break
            return chunks

        tokens = self._encoding.encode(text)
        chunks = []
        start = 0

        while start < len(tokens):
            end = min(start + chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]
            chunks.append(self._encoding.decode(chunk_tokens))
            start = end - overlap_tokens
            if start >= len(tokens):
                break

        return chunks

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int = 0,
    ) -> float:
        """Estimate API cost in USD."""
        costs = MODEL_COSTS.get(self.model_name, {"input": 0.003, "output": 0.006})
        input_cost = (input_tokens / 1000) * costs["input"]
        output_cost = (output_tokens / 1000) * costs["output"]
        return round(input_cost + output_cost, 6)

    def optimize_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        context: str,
        max_context_tokens: int,
    ) -> str:
        """
        Optimize prompt to fit within context window.
        Truncates context while preserving system and user prompts.
        """
        system_tokens = self.count_tokens(system_prompt)
        user_tokens = self.count_tokens(user_prompt)
        overhead = 50  # Buffer for message formatting

        available_context = max_context_tokens - system_tokens - user_tokens - overhead

        if available_context <= 0:
            logger.warning(
                "System + user prompt already exceeds context budget (%d tokens)",
                system_tokens + user_tokens,
            )
            return ""

        return self.truncate_to_fit(context, available_context)

    @staticmethod
    def get_model_info(model_name: str) -> Dict[str, Union[int, float]]:
        """Get token limits and costs for a model."""
        return {
            "max_tokens": MODEL_TOKEN_LIMITS.get(model_name, 0),
            "max_output_tokens": MODEL_MAX_OUTPUT_TOKENS.get(model_name, 0),
            "input_cost_per_1k": MODEL_COSTS.get(model_name, {}).get("input", 0),
            "output_cost_per_1k": MODEL_COSTS.get(model_name, {}).get("output", 0),
        }
