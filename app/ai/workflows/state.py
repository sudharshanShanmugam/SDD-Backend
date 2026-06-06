"""
LangGraph State Definitions

Defines all state types used in the SDLC workflow graph.
State is passed between nodes and persisted via the PostgreSQL checkpointer.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class WorkflowError(TypedDict):
    """Represents an error that occurred during workflow execution."""
    stage: str
    error_type: str
    message: str
    timestamp: str
    retry_count: int


class ReviewFeedback(TypedDict):
    """Human reviewer feedback for a workflow stage."""
    reviewer_id: str
    reviewer_name: str
    approved: bool
    comments: str
    requested_changes: List[str]
    timestamp: str


class SDLCWorkflowState(TypedDict):
    """
    Complete state for the SDLC workflow.

    This state is shared across all LangGraph nodes and persisted
    to PostgreSQL via the async checkpointer on every state transition.

    Fields are grouped by workflow phase for clarity.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    workflow_run_id: str
    project_id: str
    organization_id: str
    created_by: str

    # ── Document Input ───────────────────────────────────────────────────────
    document_id: str
    document_content: str
    document_chunks: List[Dict[str, Any]]
    document_metadata: Dict[str, Any]

    # ── Extraction Phase ─────────────────────────────────────────────────────
    raw_requirements: List[Dict[str, Any]]
    structured_requirements: List[Dict[str, Any]]
    requirement_domains: List[Dict[str, Any]]
    requirement_conflicts: List[Dict[str, Any]]
    missing_requirements: List[Dict[str, Any]]
    ambiguous_requirements: List[Dict[str, Any]]

    # ── Epic Phase ───────────────────────────────────────────────────────────
    epics: List[Dict[str, Any]]
    epic_coverage_gaps: List[str]
    total_estimated_sprints: int

    # ── Story Phase ──────────────────────────────────────────────────────────
    user_stories: List[Dict[str, Any]]
    invest_violations: List[Dict[str, Any]]

    # ── Planning Phase ───────────────────────────────────────────────────────
    sprint_plan: Dict[str, Any]
    tasks: List[Dict[str, Any]]
    task_summary: Dict[str, Any]

    # ── Spec Phase (parallel) ────────────────────────────────────────────────
    ui_spec: Dict[str, Any]
    api_spec: Dict[str, Any]

    # ── QA Phase ─────────────────────────────────────────────────────────────
    qa_test_suites: List[Dict[str, Any]]

    # ── Analysis Phase ────────────────────────────────────────────────────────
    dependency_analysis: Dict[str, Any]
    risk_analysis: Dict[str, Any]
    traceability_matrix: Dict[str, Any]
    estimations: List[Dict[str, Any]]

    # ── Documentation ─────────────────────────────────────────────────────────
    documentation: Dict[str, Any]
    release_notes: Dict[str, Any]

    # ── Review & Approval ─────────────────────────────────────────────────────
    requirements_approved: bool
    epics_approved: bool
    stories_approved: bool
    sprint_plan_approved: bool

    # Human review feedback
    human_feedback: Optional[ReviewFeedback]
    awaiting_approval: bool
    approval_stage: str  # Which stage is awaiting approval

    # ── Workflow Control ──────────────────────────────────────────────────────
    current_stage: str
    completed_stages: List[str]
    workflow_config: Dict[str, Any]

    # ── Error Handling ────────────────────────────────────────────────────────
    errors: List[WorkflowError]
    retry_count: int
    max_retries: int

    # ── AI Metadata ───────────────────────────────────────────────────────────
    ai_model: str
    total_tokens_used: int
    confidence_scores: Dict[str, float]
    total_cost_usd: float

    # ── Messaging (LangGraph) ─────────────────────────────────────────────────
    messages: Annotated[list, add_messages]


def create_initial_state(
    workflow_run_id: str,
    project_id: str,
    organization_id: str,
    document_id: str,
    document_content: str,
    created_by: str = "system",
    workflow_config: Optional[Dict[str, Any]] = None,
) -> SDLCWorkflowState:
    """
    Create a fresh initial state for a new SDLC workflow run.

    Args:
        workflow_run_id: Unique ID for this workflow execution
        project_id: Project being analyzed
        organization_id: Organization (tenant)
        document_id: Source document ID
        document_content: Raw document text
        created_by: User or system that triggered the workflow
        workflow_config: Optional configuration overrides

    Returns:
        Initial SDLCWorkflowState with all fields initialized to defaults
    """
    default_config = {
        "auto_approve_threshold": 0.92,
        "require_human_approval_for": ["requirements", "epics", "stories"],
        "parallel_spec_generation": True,
        "generate_qa": True,
        "generate_documentation": True,
        "generate_release_notes": False,
        "sprint_length_weeks": 2,
        "team_size": 5,
        "sprint_velocity": 40,
        "num_sprints": 6,
    }

    if workflow_config:
        default_config.update(workflow_config)

    return SDLCWorkflowState(
        # Identity
        workflow_run_id=workflow_run_id,
        project_id=project_id,
        organization_id=organization_id,
        created_by=created_by,

        # Document
        document_id=document_id,
        document_content=document_content,
        document_chunks=[],
        document_metadata={},

        # Extraction
        raw_requirements=[],
        structured_requirements=[],
        requirement_domains=[],
        requirement_conflicts=[],
        missing_requirements=[],
        ambiguous_requirements=[],

        # Epics
        epics=[],
        epic_coverage_gaps=[],
        total_estimated_sprints=0,

        # Stories
        user_stories=[],
        invest_violations=[],

        # Planning
        sprint_plan={},
        tasks=[],
        task_summary={},

        # Specs
        ui_spec={},
        api_spec={},

        # QA
        qa_test_suites=[],

        # Analysis
        dependency_analysis={},
        risk_analysis={},
        traceability_matrix={},
        estimations=[],

        # Docs
        documentation={},
        release_notes={},

        # Approval
        requirements_approved=False,
        epics_approved=False,
        stories_approved=False,
        sprint_plan_approved=False,
        human_feedback=None,
        awaiting_approval=False,
        approval_stage="",

        # Control
        current_stage="initialized",
        completed_stages=[],
        workflow_config=default_config,

        # Errors
        errors=[],
        retry_count=0,
        max_retries=3,

        # AI Metadata
        ai_model="gpt-4o",
        total_tokens_used=0,
        confidence_scores={},
        total_cost_usd=0.0,

        # Messages
        messages=[],
    )
