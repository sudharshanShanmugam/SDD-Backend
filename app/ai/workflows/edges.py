"""
LangGraph Conditional Edge Functions

These functions determine the routing decisions in the SDLC workflow graph.
Each function inspects the current state and returns the name of the next node.
"""

from __future__ import annotations

import logging
from typing import Literal

from app.ai.workflows.state import SDLCWorkflowState

logger = logging.getLogger(__name__)


def is_requirements_valid(
    state: SDLCWorkflowState,
) -> Literal["valid", "invalid"]:
    """
    Check if extracted requirements pass validation.

    Returns "valid" if requirements are present and pass quality checks.
    Returns "invalid" if extraction failed or quality is too low.
    """
    requirements = state.get("raw_requirements", [])
    errors = state.get("errors", [])
    current_stage = state.get("current_stage", "")

    # Check for validation failures
    if current_stage == "validation_failed":
        logger.info("Edge: is_requirements_valid -> invalid (validation failed)")
        return "invalid"

    # Check for agent errors in this phase
    recent_errors = [
        e for e in errors
        if e.get("stage") in ("extract_requirements", "validate_requirements")
    ]
    if recent_errors:
        logger.info("Edge: is_requirements_valid -> invalid (extraction errors)")
        return "invalid"

    if not requirements:
        logger.info("Edge: is_requirements_valid -> invalid (empty requirements)")
        return "invalid"

    logger.info(
        "Edge: is_requirements_valid -> valid (%d requirements)", len(requirements)
    )
    return "valid"


def should_await_requirements_approval(
    state: SDLCWorkflowState,
) -> Literal["await_approval", "auto_approve", "error"]:
    """
    Decide whether to interrupt for human approval of requirements.

    Returns:
        "await_approval" - pause for human review
        "auto_approve" - confidence is high enough to proceed automatically
        "error" - something went wrong, route to error handler
    """
    current_stage = state.get("current_stage", "")
    errors = state.get("errors", [])

    if current_stage == "error" or current_stage.startswith("error"):
        return "error"

    if errors:
        recent = [e for e in errors if e.get("stage") in ("extract_requirements", "structure_requirements")]
        if recent:
            return "error"

    config = state.get("workflow_config", {})
    require_approval_for = config.get("require_human_approval_for", ["requirements"])

    if "requirements" not in require_approval_for:
        return "auto_approve"

    # Check confidence threshold for auto-approval
    confidence_scores = state.get("confidence_scores", {})
    extraction_confidence = confidence_scores.get("extraction", 0.0)
    auto_approve_threshold = config.get("auto_approve_threshold", 0.92)

    if extraction_confidence >= auto_approve_threshold:
        logger.info(
            "Edge: should_await_requirements_approval -> auto_approve "
            "(confidence=%.2f >= threshold=%.2f)",
            extraction_confidence,
            auto_approve_threshold,
        )
        return "auto_approve"

    logger.info(
        "Edge: should_await_requirements_approval -> await_approval "
        "(confidence=%.2f < threshold=%.2f)",
        extraction_confidence,
        auto_approve_threshold,
    )
    return "await_approval"


def has_requirements_approval(
    state: SDLCWorkflowState,
) -> Literal["approved", "rejected", "pending"]:
    """
    Check human approval status for requirements.

    Called after the human interrupt node resumes.
    Reads from human_feedback injected by the API endpoint.
    """
    feedback = state.get("human_feedback")
    if feedback is None:
        return "pending"

    approval_stage = state.get("approval_stage", "")
    if approval_stage != "requirements":
        return "pending"

    if feedback.get("approved", False):
        logger.info("Edge: has_requirements_approval -> approved")
        return "approved"

    logger.info("Edge: has_requirements_approval -> rejected")
    return "rejected"


def should_await_epics_approval(
    state: SDLCWorkflowState,
) -> Literal["await_approval", "auto_approve", "error"]:
    """Decide whether to interrupt for epic review."""
    current_stage = state.get("current_stage", "")
    errors = state.get("errors", [])

    if current_stage == "error":
        return "error"

    recent_errors = [e for e in errors if e.get("stage") == "generate_epics"]
    if recent_errors:
        return "error"

    config = state.get("workflow_config", {})
    require_approval_for = config.get("require_human_approval_for", [])

    if "epics" not in require_approval_for:
        return "auto_approve"

    confidence_scores = state.get("confidence_scores", {})
    epic_confidence = confidence_scores.get("epics", 0.0)
    threshold = config.get("auto_approve_threshold", 0.92)

    if epic_confidence >= threshold:
        return "auto_approve"

    return "await_approval"


def has_epics_approval(
    state: SDLCWorkflowState,
) -> Literal["approved", "rejected", "pending"]:
    """Check human approval status for epics."""
    feedback = state.get("human_feedback")
    if not feedback:
        return "pending"
    if state.get("approval_stage") != "epics":
        return "pending"
    return "approved" if feedback.get("approved", False) else "rejected"


def should_await_stories_approval(
    state: SDLCWorkflowState,
) -> Literal["await_approval", "auto_approve", "error"]:
    """Decide whether to interrupt for story review."""
    current_stage = state.get("current_stage", "")

    if current_stage == "error":
        return "error"

    config = state.get("workflow_config", {})
    require_approval_for = config.get("require_human_approval_for", [])

    if "stories" not in require_approval_for:
        return "auto_approve"

    confidence_scores = state.get("confidence_scores", {})
    threshold = config.get("auto_approve_threshold", 0.92)

    # Average confidence across all story generation
    story_confidence = confidence_scores.get("stories", 0.0)
    if story_confidence >= threshold:
        return "auto_approve"

    return "await_approval"


def has_stories_approval(
    state: SDLCWorkflowState,
) -> Literal["approved", "rejected", "pending"]:
    """Check human approval status for stories."""
    feedback = state.get("human_feedback")
    if not feedback:
        return "pending"
    if state.get("approval_stage") != "stories":
        return "pending"
    return "approved" if feedback.get("approved", False) else "rejected"


def should_retry_or_fail(
    state: SDLCWorkflowState,
) -> Literal["retry", "fail"]:
    """Determine if error recovery should retry or permanently fail."""
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if retry_count < max_retries:
        return "retry"
    return "fail"


def should_generate_release_notes(
    state: SDLCWorkflowState,
) -> Literal["yes", "no"]:
    """Check if release notes generation is configured."""
    config = state.get("workflow_config", {})
    if config.get("generate_release_notes", False):
        return "yes"
    return "no"
