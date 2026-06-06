"""
Human Review Workflow

Manages the human review process for AI-generated artifacts.
Supports multi-reviewer workflows with consensus requirements.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


class ReviewItem(TypedDict):
    item_id: str
    item_type: str  # requirement|epic|story|sprint_plan
    item_data: Dict[str, Any]
    ai_confidence: float
    review_notes: str


class ReviewerDecision(TypedDict):
    reviewer_id: str
    reviewer_name: str
    decision: str  # approved|rejected|needs_revision
    comments: str
    suggested_changes: List[str]
    timestamp: str


class ReviewWorkflowState(TypedDict):
    review_session_id: str
    workflow_run_id: str
    organization_id: str

    items_to_review: List[ReviewItem]
    current_item_index: int

    reviewer_decisions: List[ReviewerDecision]
    required_approver_count: int

    # Overall review outcome
    all_approved: bool
    rejected_items: List[str]
    revision_requests: List[Dict[str, Any]]

    current_stage: str
    errors: List[str]


async def present_review_items_node(state: ReviewWorkflowState) -> Dict[str, Any]:
    """Prepare items for human review presentation."""
    items = state.get("items_to_review", [])
    logger.info(
        "review_workflow: presenting %d items for review | session=%s",
        len(items),
        state["review_session_id"],
    )
    return {"current_stage": "items_presented"}


async def collect_review_decisions_node(state: ReviewWorkflowState) -> Dict[str, Any]:
    """
    Interrupt node: pause and wait for reviewer decisions.
    In production, this is where the API waits for reviewer input.
    """
    logger.info(
        "review_workflow: awaiting reviewer decisions | session=%s",
        state["review_session_id"],
    )
    return {"current_stage": "awaiting_decisions"}


async def evaluate_decisions_node(state: ReviewWorkflowState) -> Dict[str, Any]:
    """Evaluate collected decisions and determine overall outcome."""
    decisions = state.get("reviewer_decisions", [])
    required = state.get("required_approver_count", 1)

    approvals = [d for d in decisions if d.get("decision") == "approved"]
    rejections = [d for d in decisions if d.get("decision") == "rejected"]
    revisions = [d for d in decisions if d.get("decision") == "needs_revision"]

    all_approved = len(approvals) >= required and not rejections

    revision_requests = []
    for d in revisions:
        revision_requests.extend([
            {"change": c, "reviewer": d.get("reviewer_name")}
            for c in d.get("suggested_changes", [])
        ])

    return {
        "all_approved": all_approved,
        "rejected_items": [d.get("reviewer_id") for d in rejections],
        "revision_requests": revision_requests,
        "current_stage": "decisions_evaluated",
    }


def has_enough_approvals(state: ReviewWorkflowState) -> str:
    """Check if we have enough approvals to proceed."""
    if state.get("all_approved"):
        return "approved"
    if state.get("rejected_items"):
        return "rejected"
    return "needs_revision"


class ReviewWorkflow:
    """Human review workflow for AI-generated artifacts."""

    def __init__(self):
        self._graph = None

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(ReviewWorkflowState)

        graph.add_node("present_review_items", present_review_items_node)
        graph.add_node("collect_review_decisions", collect_review_decisions_node)
        graph.add_node("evaluate_decisions", evaluate_decisions_node)

        graph.add_edge(START, "present_review_items")
        graph.add_edge("present_review_items", "collect_review_decisions")
        graph.add_edge("collect_review_decisions", "evaluate_decisions")

        graph.add_conditional_edges(
            "evaluate_decisions",
            has_enough_approvals,
            {
                "approved": END,
                "rejected": END,
                "needs_revision": "present_review_items",
            },
        )

        return graph

    async def start_review(
        self,
        review_session_id: str,
        workflow_run_id: str,
        organization_id: str,
        items: List[ReviewItem],
        required_approvers: int = 1,
    ) -> ReviewWorkflowState:
        """Start a review session."""
        if self._graph is None:
            self._graph = self._build_graph().compile(
                interrupt_before=["collect_review_decisions"]
            )

        initial_state = ReviewWorkflowState(
            review_session_id=review_session_id,
            workflow_run_id=workflow_run_id,
            organization_id=organization_id,
            items_to_review=items,
            current_item_index=0,
            reviewer_decisions=[],
            required_approver_count=required_approvers,
            all_approved=False,
            rejected_items=[],
            revision_requests=[],
            current_stage="initialized",
            errors=[],
        )

        result = await self._graph.ainvoke(initial_state)
        return result
