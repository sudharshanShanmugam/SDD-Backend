"""
Guardrails Module

Input/output safety guardrails for the AI pipeline:
- Prompt injection detection
- PII detection and masking
- Output schema validation
- Toxicity filtering
- Per-organization rate limiting
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── PII Detection Patterns ──────────────────────────────────────────────────

PII_PATTERNS: List[Tuple[str, str, str]] = [
    # (pattern_name, regex, replacement)
    ("email", r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "[EMAIL]"),
    ("phone_us", r"\b(\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "[PHONE]"),
    ("phone_intl", r"\+\d{1,3}[-.\s]?\d{2,4}[-.\s]?\d{4,10}", "[PHONE]"),
    ("ssn", r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b", "[SSN]"),
    ("credit_card", r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "[CREDIT_CARD]"),
    ("ip_address", r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP_ADDRESS]"),
    ("aws_key", r"AKIA[0-9A-Z]{16}", "[AWS_KEY]"),
    ("generic_api_key", r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9+/=\-_]{20,}", "[API_KEY]"),
    ("private_key_header", r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "[PRIVATE_KEY]"),
    ("password", r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{6,}", "[PASSWORD]"),
]


# ── Prompt Injection Patterns ────────────────────────────────────────────────

INJECTION_PATTERNS: List[str] = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"forget\s+(everything|all)\s+(you|i|we)\s+(said|told|instructed)",
    r"you\s+are\s+now\s+(?!a\s+(software|business|product|qa|tech|scrum))",
    r"act\s+as\s+(?!a\s+(software|business|product|qa|tech|scrum))",
    r"disregard\s+(your|the|all)\s+(instructions?|guidelines?|rules?|constraints?)",
    r"jailbreak",
    r"DAN\b",
    r"bypass\s+(the\s+)?(safety|security|guardrails?|filters?)",
    r"pretend\s+you\s+(have\s+no|are\s+not)",
    r"system\s+prompt\s*:",
    r"<\|im_start\|>",
    r"\[INST\]",
    r"<s>",
]


# ── Toxicity Keywords (simplified; production should use a model) ─────────────

TOXICITY_CATEGORIES = {
    "hate_speech": [
        "slur_placeholder_1",  # Replace with actual patterns in production
        "slur_placeholder_2",
    ],
    "violence": [
        "kill", "murder", "bomb", "explosive",
        "weapon", "shoot", "stabbing",
    ],
    "sexual_content": [
        "explicit_content_placeholder",
    ],
}


class RateLimiter:
    """
    In-process rate limiter using sliding window algorithm.

    For production, replace with Redis-backed rate limiting
    (e.g., using redis-py with ZADD/ZRANGEBYSCORE).
    """

    def __init__(self, requests_per_minute: int, requests_per_day: int):
        self.rpm = requests_per_minute
        self.rpd = requests_per_day
        # org_id -> [timestamps]
        self._minute_windows: Dict[str, List[float]] = defaultdict(list)
        self._day_windows: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, org_id: str) -> Tuple[bool, Optional[str]]:
        """Check if a request is allowed for the organization."""
        now = time.time()
        minute_ago = now - 60
        day_ago = now - 86400

        # Clean old entries
        self._minute_windows[org_id] = [
            t for t in self._minute_windows[org_id] if t > minute_ago
        ]
        self._day_windows[org_id] = [
            t for t in self._day_windows[org_id] if t > day_ago
        ]

        # Check limits
        if len(self._minute_windows[org_id]) >= self.rpm:
            return False, f"Rate limit exceeded: {self.rpm} requests/minute"

        if len(self._day_windows[org_id]) >= self.rpd:
            return False, f"Daily quota exceeded: {self.rpd} requests/day"

        # Record the request
        self._minute_windows[org_id].append(now)
        self._day_windows[org_id].append(now)
        return True, None


class GuardrailViolation(Exception):
    """Raised when a guardrail check fails."""

    def __init__(self, violation_type: str, message: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.violation_type = violation_type
        self.details = details or {}


class GuardrailResult:
    """Result of a guardrail check."""

    def __init__(self):
        self.passed = True
        self.violations: List[Dict[str, str]] = []
        self.warnings: List[str] = []
        self.sanitized_text: Optional[str] = None
        self.pii_detected: bool = False
        self.injection_detected: bool = False
        self.toxicity_detected: bool = False

    def add_violation(self, type_: str, message: str):
        self.passed = False
        self.violations.append({"type": type_, "message": message})

    def add_warning(self, message: str):
        self.warnings.append(message)


class Guardrails:
    """
    Comprehensive input/output safety guardrails.

    Usage:
        guardrails = Guardrails()

        # Check input before sending to LLM
        result = await guardrails.check_input(text, org_id="org_123")
        if not result.passed:
            raise GuardrailViolation(...)

        # Check output before returning to user
        result = await guardrails.check_output(response, expected_schema=MyModel)
    """

    def __init__(self):
        from app.ai.config import AIConfig

        self.config = AIConfig.GUARDRAILS
        self._pii_patterns = [(name, re.compile(pattern, re.IGNORECASE), replacement)
                              for name, pattern, replacement in PII_PATTERNS]
        self._injection_patterns = [
            re.compile(p, re.IGNORECASE | re.MULTILINE)
            for p in INJECTION_PATTERNS
        ]
        self._rate_limiter = RateLimiter(
            requests_per_minute=self.config.rate_limit_per_org_per_minute,
            requests_per_day=self.config.rate_limit_per_org_per_day,
        )

    async def check_input(
        self,
        text: str,
        org_id: str = "default",
        mask_pii: bool = True,
    ) -> GuardrailResult:
        """
        Check and sanitize input text before sending to LLM.

        Checks:
        1. Rate limiting
        2. Token size limits
        3. Prompt injection detection
        4. PII detection/masking
        5. Toxicity detection
        """
        result = GuardrailResult()

        # 1. Rate limiting
        if self.config.enable_pii_detection:  # Only rate-limit when guardrails enabled
            allowed, reason = self._rate_limiter.is_allowed(org_id)
            if not allowed:
                result.add_violation("rate_limit", reason or "Rate limit exceeded")
                return result

        # 2. Size check
        if len(text) > self.config.max_input_tokens * 4:  # Rough char estimate
            result.add_warning(
                f"Input may be large ({len(text)} chars). "
                "Consider chunking for better results."
            )

        # 3. Prompt injection detection
        if self.config.enable_injection_detection:
            injection_result = self._detect_injection(text)
            if injection_result:
                result.injection_detected = True
                result.add_violation(
                    "prompt_injection",
                    f"Potential prompt injection detected: {injection_result}",
                )
                # Don't process further if injection detected
                return result

        # 4. PII detection and masking
        if self.config.enable_pii_detection:
            masked_text, pii_found = self._mask_pii(text)
            if pii_found:
                result.pii_detected = True
                result.sanitized_text = masked_text if mask_pii else text
                result.add_warning(
                    f"PII detected and {'masked' if mask_pii else 'flagged'}: "
                    f"{', '.join(pii_found[:5])}"
                )
            else:
                result.sanitized_text = text
        else:
            result.sanitized_text = text

        # 5. Toxicity check
        if self.config.enable_toxicity_filter:
            toxicity_result = self._detect_toxicity(text)
            if toxicity_result:
                result.toxicity_detected = True
                result.add_violation(
                    "toxicity",
                    f"Toxic content detected: {toxicity_result}",
                )

        return result

    async def check_output(
        self,
        output: Any,
        expected_schema: Optional[type] = None,
    ) -> GuardrailResult:
        """
        Validate and sanitize LLM output before returning to application.

        Checks:
        1. Schema validation (if schema provided)
        2. PII in output (shouldn't expose PII)
        3. Output toxicity
        4. Size limits
        """
        result = GuardrailResult()

        # Convert to string for text-based checks
        if isinstance(output, str):
            output_text = output
        elif hasattr(output, "model_dump"):
            output_text = json.dumps(output.model_dump(), indent=2)
        elif isinstance(output, dict):
            output_text = json.dumps(output, indent=2)
        else:
            output_text = str(output)

        # 1. Schema validation
        if expected_schema is not None:
            try:
                if isinstance(output, dict):
                    expected_schema.model_validate(output)
                elif hasattr(output, "model_dump"):
                    # Already a Pydantic model, check it's the right type
                    if not isinstance(output, expected_schema):
                        result.add_warning(
                            f"Output type {type(output).__name__} doesn't match "
                            f"expected {expected_schema.__name__}"
                        )
            except Exception as e:
                result.add_violation("schema_validation", f"Output schema invalid: {e}")

        # 2. PII in output
        if self.config.enable_pii_detection:
            _, pii_found = self._mask_pii(output_text)
            if pii_found:
                result.pii_detected = True
                result.add_warning(
                    f"PII detected in output: {', '.join(pii_found[:3])}. "
                    "Review before returning to client."
                )

        # 3. Toxicity check on output
        if self.config.enable_toxicity_filter:
            toxicity = self._detect_toxicity(output_text)
            if toxicity:
                result.toxicity_detected = True
                result.add_violation("toxicity", f"Toxic content in output: {toxicity}")

        # 4. Output size check
        if len(output_text) > self.config.max_output_tokens * 5:
            result.add_warning(
                f"Output is very large ({len(output_text)} chars). "
                "Consider paginating or summarizing."
            )

        return result

    def _detect_injection(self, text: str) -> Optional[str]:
        """Detect prompt injection attempts. Returns matched pattern or None."""
        for pattern in self._injection_patterns:
            match = pattern.search(text)
            if match:
                return match.group(0)[:100]  # Return first 100 chars of match
        return None

    def _mask_pii(self, text: str) -> Tuple[str, List[str]]:
        """
        Detect and mask PII in text.
        Returns (masked_text, list_of_pii_types_found).
        """
        masked = text
        found_types = []

        for name, pattern, replacement in self._pii_patterns:
            if pattern.search(masked):
                masked = pattern.sub(replacement, masked)
                found_types.append(name)

        return masked, found_types

    def _detect_toxicity(self, text: str) -> Optional[str]:
        """
        Basic toxicity detection.
        Returns category of toxicity found or None.

        Note: In production, replace with a proper toxicity model
        (e.g., Perspective API or a fine-tuned classifier).
        """
        text_lower = text.lower()

        for category, keywords in TOXICITY_CATEGORIES.items():
            if category in ("hate_speech", "sexual_content"):
                # Skip placeholder categories
                continue
            for keyword in keywords:
                if f" {keyword} " in f" {text_lower} ":
                    return category

        return None

    def hash_sensitive_data(self, text: str) -> str:
        """Create a consistent hash of sensitive data for logging."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def get_rate_limit_status(self, org_id: str) -> Dict[str, Any]:
        """Get current rate limit status for an organization."""
        now = time.time()
        minute_ago = now - 60
        day_ago = now - 86400

        minute_count = len([
            t for t in self._rate_limiter._minute_windows.get(org_id, [])
            if t > minute_ago
        ])
        day_count = len([
            t for t in self._rate_limiter._day_windows.get(org_id, [])
            if t > day_ago
        ])

        return {
            "org_id": org_id,
            "requests_this_minute": minute_count,
            "requests_today": day_count,
            "minute_limit": self._rate_limiter.rpm,
            "day_limit": self._rate_limiter.rpd,
            "minute_remaining": max(0, self._rate_limiter.rpm - minute_count),
            "day_remaining": max(0, self._rate_limiter.rpd - day_count),
        }
