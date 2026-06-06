"""
Confidence Scorer Module

Multi-factor confidence scoring for AI-generated artifacts.
Evaluates completeness, clarity, consistency, and coverage of outputs.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# Ambiguity indicators that reduce clarity score
AMBIGUITY_PATTERNS = [
    r"\bTBD\b",
    r"\bTBA\b",
    r"\bto be (determined|defined|confirmed|discussed)\b",
    r"\bsomehow\b",
    r"\bpossibly\b",
    r"\bmaybe\b",
    r"\bperhaps\b",
    r"\bsome kind of\b",
    r"\betc\.\b",
    r"\band so on\b",
    r"\bvarious\b",
    r"\bmight\b",
    r"\bcould potentially\b",
    r"\bappropriate\b",
    r"\bsuitable\b",
    r"\bif needed\b",
    r"\bif necessary\b",
    r"\bwhen applicable\b",
]

# Required fields per artifact type
REQUIRED_FIELDS: Dict[str, List[str]] = {
    "requirement_extraction": [
        "functional_requirements",
        "non_functional_requirements",
        "constraints",
        "assumptions",
    ],
    "epic_generation": [
        "epics",
        "grouping_rationale",
        "coverage_gaps",
        "total_estimated_sprints",
    ],
    "story_generation": [
        "stories",
        "invest_analysis",
    ],
    "qa_generation": [
        "test_suite",
    ],
    "api_spec_generation": [
        "openapi",
        "info",
        "paths",
        "components",
    ],
    "sprint_planning": [
        "sprint_plan",
    ],
    "task_breakdown": [
        "tasks",
        "summary",
    ],
}


class ConfidenceBreakdown(BaseModel):
    """Detailed confidence score breakdown."""

    completeness: float = 0.0  # 0-1: are all required fields present?
    clarity: float = 0.0       # 0-1: is the output unambiguous?
    consistency: float = 0.0   # 0-1: is the output internally consistent?
    coverage: float = 0.0      # 0-1: does it cover all inputs?
    specificity: float = 0.0   # 0-1: are descriptions specific enough?
    overall: float = 0.0       # weighted average
    issues: List[str] = []
    suggestions: List[str] = []


class ConfidenceScorer:
    """
    Multi-factor confidence scoring for AI-generated artifacts.

    Scoring dimensions:
    - Completeness: All required fields are present and non-empty
    - Clarity: Output is unambiguous (no TBD, vague language)
    - Consistency: No internal contradictions
    - Coverage: All input requirements/stories are addressed
    - Specificity: Descriptions are detailed enough to act on
    """

    # Weights for overall score calculation
    WEIGHTS = {
        "completeness": 0.30,
        "clarity": 0.25,
        "consistency": 0.20,
        "coverage": 0.15,
        "specificity": 0.10,
    }

    async def score(
        self,
        task_name: str,
        output: Any,
        input_data: Dict[str, Any],
    ) -> Dict[str, float]:
        """
        Score an AI output for confidence.

        Returns a dict with component scores and overall confidence.
        """
        if output is None:
            return {"overall": 0.0, "completeness": 0.0}

        # Convert Pydantic model to dict for analysis
        if hasattr(output, "model_dump"):
            output_dict = output.model_dump()
        elif isinstance(output, dict):
            output_dict = output
        else:
            output_dict = {"data": str(output)}

        breakdown = ConfidenceBreakdown()
        output_text = self._to_text(output_dict)

        # Score each dimension
        breakdown.completeness = self._score_completeness(
            task_name, output_dict, breakdown
        )
        breakdown.clarity = self._score_clarity(output_text, breakdown)
        breakdown.consistency = self._score_consistency(
            task_name, output_dict, input_data, breakdown
        )
        breakdown.coverage = self._score_coverage(
            task_name, output_dict, input_data, breakdown
        )
        breakdown.specificity = self._score_specificity(output_text, breakdown)

        # Calculate weighted overall score
        breakdown.overall = sum(
            getattr(breakdown, dim) * weight
            for dim, weight in self.WEIGHTS.items()
        )

        logger.debug(
            "Confidence scores for %s: overall=%.2f, completeness=%.2f, "
            "clarity=%.2f, consistency=%.2f, coverage=%.2f, specificity=%.2f",
            task_name,
            breakdown.overall,
            breakdown.completeness,
            breakdown.clarity,
            breakdown.consistency,
            breakdown.coverage,
            breakdown.specificity,
        )

        return breakdown.model_dump()

    def _score_completeness(
        self,
        task_name: str,
        output: Dict,
        breakdown: ConfidenceBreakdown,
    ) -> float:
        """Score completeness: are all required fields present and non-empty?"""
        required = REQUIRED_FIELDS.get(task_name, [])
        if not required:
            return 0.85  # No required fields defined; give benefit of doubt

        present_count = 0
        for field in required:
            value = output.get(field)
            if value is not None and value != "" and value != [] and value != {}:
                present_count += 1
            else:
                breakdown.issues.append(f"Missing or empty required field: {field}")
                breakdown.suggestions.append(
                    f"Ensure the '{field}' field is populated in the output"
                )

        base_score = present_count / len(required) if required else 1.0

        # Penalty for items within lists that have empty critical fields
        list_completeness = self._check_list_completeness(output)
        final_score = (base_score * 0.7) + (list_completeness * 0.3)

        return round(final_score, 3)

    def _check_list_completeness(self, output: Dict) -> float:
        """Check that list items have their own required fields."""
        penalties = 0
        total_checks = 0

        for key, value in output.items():
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                # Check for commonly required item fields
                for critical_field in ["id", "title", "description"]:
                    if critical_field in item:
                        total_checks += 1
                        if not item[critical_field]:
                            penalties += 1

        if total_checks == 0:
            return 1.0

        return max(0.0, 1.0 - (penalties / total_checks))

    def _score_clarity(
        self,
        text: str,
        breakdown: ConfidenceBreakdown,
    ) -> float:
        """Score clarity: how free of ambiguous language is the output?"""
        if not text:
            return 0.5

        text_lower = text.lower()
        total_sentences = max(1, text.count(".") + text.count("!") + text.count("?"))
        ambiguity_hits = 0

        for pattern in AMBIGUITY_PATTERNS:
            matches = re.findall(pattern, text_lower)
            if matches:
                ambiguity_hits += len(matches)
                # Report first few occurrences
                if ambiguity_hits <= 3:
                    breakdown.issues.append(
                        f"Ambiguous language detected: '{matches[0]}'"
                    )

        # Normalize: penalty per sentence
        ambiguity_density = ambiguity_hits / total_sentences
        clarity = max(0.0, 1.0 - (ambiguity_density * 2))

        # Bonus: check for specific, measurable language
        specific_patterns = [
            r"\d+%",           # Percentages
            r"\d+\s*(ms|s|hours?|days?|weeks?)",  # Time measurements
            r"\d+\s*(MB|GB|KB|TB)",  # Data sizes
            r"\b[A-Z]{2,}-\d+\b",   # IDs like FR-001
            r"\bRFC\s+\d+\b",       # RFC references
        ]
        specificity_bonus = sum(
            0.02 for p in specific_patterns if re.search(p, text)
        )
        clarity = min(1.0, clarity + specificity_bonus)

        return round(clarity, 3)

    def _score_consistency(
        self,
        task_name: str,
        output: Dict,
        input_data: Dict,
        breakdown: ConfidenceBreakdown,
    ) -> float:
        """Score consistency: no internal contradictions."""
        score = 1.0
        issues_found = 0

        # Check story point consistency (if applicable)
        if "stories" in output:
            for story in output.get("stories", []):
                points = story.get("story_points", 0)
                if points and points > 13:
                    breakdown.issues.append(
                        f"Story {story.get('id', '?')} has {points} points - "
                        "should be split (max 13)"
                    )
                    issues_found += 1

        # Check priority consistency
        if "epics" in output and "stories" in output:
            epic_priorities = {
                e["id"]: e.get("priority") for e in output.get("epics", [])
                if isinstance(e, dict) and "id" in e
            }
            for story in output.get("stories", []):
                if not isinstance(story, dict):
                    continue
                epic_id = story.get("epic_id")
                if epic_id and epic_id in epic_priorities:
                    epic_priority = epic_priorities[epic_id]
                    story_priority = story.get("priority")
                    # A critical story in a could_have epic is suspicious
                    if (
                        epic_priority == "could_have"
                        and story_priority == "critical"
                    ):
                        breakdown.issues.append(
                            f"Story {story.get('id')} is critical but its epic "
                            f"{epic_id} is could_have - review priority alignment"
                        )
                        issues_found += 1

        # Penalize per issue found
        penalty = min(0.4, issues_found * 0.1)
        return round(max(0.0, score - penalty), 3)

    def _score_coverage(
        self,
        task_name: str,
        output: Dict,
        input_data: Dict,
        breakdown: ConfidenceBreakdown,
    ) -> float:
        """Score coverage: are all inputs addressed in the output?"""
        if task_name == "epic_generation":
            return self._score_epic_coverage(output, input_data, breakdown)
        elif task_name == "story_generation":
            return self._score_story_coverage(output, input_data, breakdown)
        elif task_name == "qa_generation":
            return self._score_qa_coverage(output, input_data, breakdown)
        return 0.85  # Default for unchecked task types

    def _score_epic_coverage(
        self,
        output: Dict,
        input_data: Dict,
        breakdown: ConfidenceBreakdown,
    ) -> float:
        """Check that all requirements are covered by at least one epic."""
        requirements = input_data.get("requirements", [])
        if not requirements:
            return 0.85

        # Collect all requirement IDs referenced in epics
        covered_req_ids = set()
        for epic in output.get("epics", []):
            if isinstance(epic, dict):
                covered_req_ids.update(epic.get("requirement_ids", []))

        total = len(requirements)
        if total == 0:
            return 1.0

        req_ids = {
            r.get("id") for r in requirements
            if isinstance(r, dict) and r.get("id")
        }
        uncovered = req_ids - covered_req_ids

        if uncovered:
            breakdown.issues.append(
                f"{len(uncovered)} requirements not covered by any epic: "
                f"{', '.join(list(uncovered)[:5])}"
            )

        return round(1.0 - (len(uncovered) / max(1, total)), 3)

    def _score_story_coverage(
        self,
        output: Dict,
        input_data: Dict,
        breakdown: ConfidenceBreakdown,
    ) -> float:
        """Check that epic acceptance criteria are addressed by stories."""
        epic = input_data.get("epic", {})
        if not epic:
            return 0.85

        ac_count = len(epic.get("acceptance_criteria", []))
        stories = output.get("stories", [])

        if ac_count == 0 or not stories:
            return 0.75

        # Heuristic: expect at least 1 story per acceptance criterion
        story_count = len(stories)
        coverage_ratio = min(1.0, story_count / max(1, ac_count))

        if coverage_ratio < 0.5:
            breakdown.suggestions.append(
                f"Only {story_count} stories for {ac_count} acceptance criteria - "
                "consider adding more granular stories"
            )

        return round(coverage_ratio, 3)

    def _score_qa_coverage(
        self,
        output: Dict,
        input_data: Dict,
        breakdown: ConfidenceBreakdown,
    ) -> float:
        """Check QA coverage against acceptance criteria."""
        test_suite = output.get("test_suite", {})
        coverage_analysis = test_suite.get("coverage_analysis", {})
        coverage_pct = coverage_analysis.get("coverage_percent", 0)

        if coverage_pct > 0:
            return coverage_pct / 100.0

        # Fallback: count test types
        test_cases = test_suite.get("test_cases", [])
        has_functional = any(
            tc.get("type") == "functional" for tc in test_cases
        )
        has_negative = any(
            tc.get("type") == "negative" for tc in test_cases
        )
        has_edge = any(
            tc.get("type") == "edge_case" for tc in test_cases
        )

        type_coverage = sum([has_functional, has_negative, has_edge]) / 3
        return round(type_coverage, 3)

    def _score_specificity(
        self,
        text: str,
        breakdown: ConfidenceBreakdown,
    ) -> float:
        """Score specificity: are descriptions detailed and actionable?"""
        if not text:
            return 0.0

        words = text.split()
        if not words:
            return 0.0

        # Penalize very short descriptions
        avg_words_per_sentence = len(words) / max(
            1, text.count(".") + text.count("!")
        )
        if avg_words_per_sentence < 5:
            breakdown.suggestions.append(
                "Descriptions are too brief - add more technical detail"
            )
            return 0.4

        # Check for technical specificity indicators
        technical_terms = [
            r"\bAPI\b", r"\bREST\b", r"\bHTTP[S]?\b", r"\bGET|POST|PUT|DELETE\b",
            r"\bJSON\b", r"\bSQL\b", r"\bOAuth\b", r"\bJWT\b",
            r"\bDatabase\b", r"\bEndpoint\b", r"\bComponent\b",
            r"\b[A-Z][a-zA-Z]+Service\b", r"\b[A-Z][a-zA-Z]+Repository\b",
        ]
        tech_hit_count = sum(
            1 for p in technical_terms if re.search(p, text)
        )

        # Normalize
        specificity = min(1.0, 0.5 + (tech_hit_count * 0.05))
        return round(specificity, 3)

    def _to_text(self, obj: Any) -> str:
        """Recursively convert object to plain text for analysis."""
        if isinstance(obj, str):
            return obj
        elif isinstance(obj, dict):
            return " ".join(self._to_text(v) for v in obj.values())
        elif isinstance(obj, list):
            return " ".join(self._to_text(item) for item in obj)
        elif obj is None:
            return ""
        else:
            return str(obj)

    def should_auto_approve(self, confidence: float) -> bool:
        """Check if confidence is high enough for auto-approval."""
        from app.ai.config import AIConfig
        return confidence >= AIConfig.AUTO_APPROVE_THRESHOLD

    def needs_human_review(self, confidence: float) -> bool:
        """Check if confidence is too low and requires human review."""
        from app.ai.config import AIConfig
        return confidence < AIConfig.MIN_CONFIDENCE_THRESHOLD
