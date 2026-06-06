"""
Main SDLC LangGraph Workflow

Implements the complete Software Development Lifecycle workflow as a
stateful LangGraph StateGraph with:
- Human-in-the-loop approval checkpoints
- Parallel execution for UI/API spec generation
- PostgreSQL-backed checkpointing for resumability
- Automatic error recovery with retry logic
- Conditional routing based on confidence scores and approval status
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncIterator, Dict, Optional

try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    _POSTGRES_CHECKPOINTER_AVAILABLE = True
except ImportError:
    _POSTGRES_CHECKPOINTER_AVAILABLE = False
    AsyncPostgresSaver = None  # type: ignore

from langgraph.graph import END, START, StateGraph
from langgraph.graph.graph import CompiledGraph

from app.ai.workflows.edges import (
    has_epics_approval,
    has_requirements_approval,
    has_stories_approval,
    is_requirements_valid,
    should_await_epics_approval,
    should_await_requirements_approval,
    should_await_stories_approval,
    should_generate_release_notes,
)
from app.ai.workflows.nodes import (
    await_epics_approval_node,
    await_requirements_approval_node,
    await_stories_approval_node,
    chunk_document_node,
    extract_requirements_node,
    finalize_workflow_node,
    generate_api_spec_node,
    generate_documentation_node,
    generate_epics_node,
    generate_qa_node,
    generate_release_notes_node,
    generate_sprint_plan_node,
    generate_stories_node,
    generate_tasks_node,
    generate_ui_spec_node,
    handle_error_node,
    structure_requirements_node,
    validate_requirements_node,
)
from app.ai.workflows.state import SDLCWorkflowState, create_initial_state

logger = logging.getLogger(__name__)


class SDLCWorkflow:
    """
    Main SDLC workflow orchestrator using LangGraph.

    Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │  chunk_document                                                   │
    │       │                                                           │
    │  extract_requirements ──(invalid)──► handle_error                │
    │       │                                                           │
    │  validate_requirements                                            │
    │       │                                                           │
    │  structure_requirements                                           │
    │       │                                                           │
    │  [await_requirements_approval?] ──(human interrupt)──►           │
    │       │ (approved)                                                │
    │  generate_epics                                                   │
    │       │                                                           │
    │  [await_epics_approval?] ──(human interrupt)──►                  │
    │       │ (approved)                                                │
    │  generate_stories                                                 │
    │       │                                                           │
    │  [await_stories_approval?] ──(human interrupt)──►                │
    │       │ (approved)                                                │
    │  generate_sprint_plan                                             │
    │       │                                                           │
    │  generate_tasks                                                   │
    │       │                                                           │
    │  ┌────┴────┐                                                      │
    │  │ generate │  (parallel)                                         │
    │  │ ui_spec  │ ─────────────────────────┐                         │
    │  └──────────┘                           ▼                        │
    │                           generate_api_spec                       │
    │  generate_qa ◄──────────────────────────┘                        │
    │       │                                                           │
    │  generate_documentation                                           │
    │       │                                                           │
    │  [generate_release_notes?]                                        │
    │       │                                                           │
    │  finalize_workflow ──► END                                        │
    └─────────────────────────────────────────────────────────────────┘

    Human interrupt nodes (LangGraph interrupt_before):
    - await_requirements_approval_node
    - await_epics_approval_node
    - await_stories_approval_node
    """

    def __init__(self, db_url: Optional[str] = None):
        from app.ai.config import AIConfig
        self.db_url = db_url or AIConfig.DATABASE_URL
        self._compiled_graph: Optional[CompiledGraph] = None
        self._checkpointer: Optional[AsyncPostgresSaver] = None

    def _build_graph(self) -> StateGraph:
        """Construct the LangGraph StateGraph with all nodes and edges."""
        graph = StateGraph(SDLCWorkflowState)

        # ── Register all nodes ───────────────────────────────────────────────
        graph.add_node("chunk_document", chunk_document_node)
        graph.add_node("extract_requirements", extract_requirements_node)
        graph.add_node("validate_requirements", validate_requirements_node)
        graph.add_node("structure_requirements", structure_requirements_node)

        # Human approval interrupt nodes
        graph.add_node("await_requirements_approval", await_requirements_approval_node)
        graph.add_node("await_epics_approval", await_epics_approval_node)
        graph.add_node("await_stories_approval", await_stories_approval_node)

        # Generation nodes
        graph.add_node("generate_epics", generate_epics_node)
        graph.add_node("generate_stories", generate_stories_node)
        graph.add_node("generate_sprint_plan", generate_sprint_plan_node)
        graph.add_node("generate_tasks", generate_tasks_node)

        # Parallel spec generation
        graph.add_node("generate_ui_spec", generate_ui_spec_node)
        graph.add_node("generate_api_spec", generate_api_spec_node)

        # QA and documentation
        graph.add_node("generate_qa", generate_qa_node)
        graph.add_node("generate_documentation", generate_documentation_node)
        graph.add_node("generate_release_notes", generate_release_notes_node)

        # Terminal nodes
        graph.add_node("finalize_workflow", finalize_workflow_node)
        graph.add_node("handle_error", handle_error_node)

        # ── Entry point ──────────────────────────────────────────────────────
        graph.add_edge(START, "chunk_document")
        graph.add_edge("chunk_document", "extract_requirements")

        # ── Requirements phase ───────────────────────────────────────────────
        graph.add_conditional_edges(
            "extract_requirements",
            is_requirements_valid,
            {
                "valid": "validate_requirements",
                "invalid": "handle_error",
            },
        )
        graph.add_edge("validate_requirements", "structure_requirements")

        # Approval gate for requirements
        graph.add_conditional_edges(
            "structure_requirements",
            should_await_requirements_approval,
            {
                "await_approval": "await_requirements_approval",
                "auto_approve": "generate_epics",
                "error": "handle_error",
            },
        )

        # After human review of requirements
        graph.add_conditional_edges(
            "await_requirements_approval",
            has_requirements_approval,
            {
                "approved": "generate_epics",
                "rejected": "extract_requirements",  # Re-extract with feedback
                "pending": "await_requirements_approval",  # Keep waiting
            },
        )

        # ── Epic phase ───────────────────────────────────────────────────────
        graph.add_conditional_edges(
            "generate_epics",
            should_await_epics_approval,
            {
                "await_approval": "await_epics_approval",
                "auto_approve": "generate_stories",
                "error": "handle_error",
            },
        )

        graph.add_conditional_edges(
            "await_epics_approval",
            has_epics_approval,
            {
                "approved": "generate_stories",
                "rejected": "generate_epics",  # Regenerate with feedback
                "pending": "await_epics_approval",
            },
        )

        # ── Story phase ──────────────────────────────────────────────────────
        graph.add_conditional_edges(
            "generate_stories",
            should_await_stories_approval,
            {
                "await_approval": "await_stories_approval",
                "auto_approve": "generate_sprint_plan",
                "error": "handle_error",
            },
        )

        graph.add_conditional_edges(
            "await_stories_approval",
            has_stories_approval,
            {
                "approved": "generate_sprint_plan",
                "rejected": "generate_stories",  # Regenerate with feedback
                "pending": "await_stories_approval",
            },
        )

        # ── Planning phase ───────────────────────────────────────────────────
        graph.add_edge("generate_sprint_plan", "generate_tasks")

        # ── Parallel spec generation ─────────────────────────────────────────
        # Both specs can run in parallel; after both complete → QA
        graph.add_edge("generate_tasks", "generate_ui_spec")
        graph.add_edge("generate_tasks", "generate_api_spec")

        # Fan-in: after both parallel nodes complete → QA
        graph.add_edge("generate_ui_spec", "generate_qa")
        graph.add_edge("generate_api_spec", "generate_qa")

        # ── QA and Documentation ─────────────────────────────────────────────
        graph.add_edge("generate_qa", "generate_documentation")

        # Optional release notes
        graph.add_conditional_edges(
            "generate_documentation",
            should_generate_release_notes,
            {
                "yes": "generate_release_notes",
                "no": "finalize_workflow",
            },
        )
        graph.add_edge("generate_release_notes", "finalize_workflow")

        # ── Termination ──────────────────────────────────────────────────────
        graph.add_edge("finalize_workflow", END)
        graph.add_edge("handle_error", END)

        return graph

    async def initialize(self) -> None:
        """Initialize the workflow with PostgreSQL checkpointer."""
        if self._compiled_graph is not None:
            return

        # Setup PostgreSQL checkpointer for workflow persistence
        if _POSTGRES_CHECKPOINTER_AVAILABLE and AsyncPostgresSaver is not None:
            try:
                self._checkpointer = AsyncPostgresSaver.from_conn_string(self.db_url)
                await self._checkpointer.setup()
                logger.info("PostgreSQL checkpointer initialized")
            except Exception as e:
                logger.warning(
                    "Failed to initialize PostgreSQL checkpointer: %s. "
                    "Using in-memory checkpointer.",
                    e,
                )
                from langgraph.checkpoint.memory import MemorySaver
                self._checkpointer = MemorySaver()
        else:
            logger.warning(
                "langgraph-checkpoint-postgres not installed. "
                "Using in-memory checkpointer (install: pip install langgraph-checkpoint-postgres)."
            )
            from langgraph.checkpoint.memory import MemorySaver
            self._checkpointer = MemorySaver()

        graph = self._build_graph()

        # Compile with interrupt_before for human-in-the-loop nodes
        self._compiled_graph = graph.compile(
            checkpointer=self._checkpointer,
            interrupt_before=[
                "await_requirements_approval",
                "await_epics_approval",
                "await_stories_approval",
            ],
        )

        logger.info("SDLC workflow graph compiled successfully")

    @property
    def graph(self) -> CompiledGraph:
        """Get the compiled graph (must call initialize() first)."""
        if self._compiled_graph is None:
            raise RuntimeError(
                "Workflow not initialized. Call await workflow.initialize() first."
            )
        return self._compiled_graph

    async def start(
        self,
        project_id: str,
        organization_id: str,
        document_id: str,
        document_content: str,
        created_by: str = "system",
        workflow_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Start a new SDLC workflow run.

        Returns:
            workflow_run_id that can be used to resume/query the workflow
        """
        await self.initialize()

        workflow_run_id = str(uuid.uuid4())

        initial_state = create_initial_state(
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            organization_id=organization_id,
            document_id=document_id,
            document_content=document_content,
            created_by=created_by,
            workflow_config=workflow_config,
        )

        config = {"configurable": {"thread_id": workflow_run_id}}

        logger.info(
            "Starting SDLC workflow | run=%s | project=%s | org=%s",
            workflow_run_id,
            project_id,
            organization_id,
        )

        # Start execution (will pause at first interrupt_before node)
        await self.graph.ainvoke(initial_state, config=config)

        return workflow_run_id

    async def resume_with_approval(
        self,
        workflow_run_id: str,
        reviewer_id: str,
        reviewer_name: str,
        approved: bool,
        comments: str = "",
        requested_changes: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Resume a paused workflow after human review.

        Args:
            workflow_run_id: The run ID to resume
            reviewer_id: ID of the reviewing user
            reviewer_name: Name of the reviewing user
            approved: Whether the current stage is approved
            comments: Reviewer comments
            requested_changes: List of specific changes requested

        Returns:
            Updated state after resumption
        """
        await self.initialize()

        from datetime import datetime, timezone

        config = {"configurable": {"thread_id": workflow_run_id}}

        # Inject human feedback into state
        feedback = {
            "reviewer_id": reviewer_id,
            "reviewer_name": reviewer_name,
            "approved": approved,
            "comments": comments,
            "requested_changes": requested_changes or [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Resume by updating state and re-invoking
        # LangGraph will continue from the checkpoint
        result = await self.graph.ainvoke(
            {"human_feedback": feedback, "awaiting_approval": False},
            config=config,
        )

        logger.info(
            "Workflow resumed | run=%s | approved=%s | stage=%s",
            workflow_run_id,
            approved,
            result.get("approval_stage", "?"),
        )

        return result

    async def get_state(self, workflow_run_id: str) -> Optional[SDLCWorkflowState]:
        """Get the current state of a workflow run."""
        await self.initialize()
        config = {"configurable": {"thread_id": workflow_run_id}}
        state = await self.graph.aget_state(config)
        if state:
            return state.values
        return None

    async def stream_events(
        self,
        workflow_run_id: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream workflow events as Server-Sent Events.

        Yields dicts with 'type' and 'data' for each event.
        """
        await self.initialize()
        config = {"configurable": {"thread_id": workflow_run_id}}

        async for event in self.graph.astream_events(
            None,  # No new input; resume from checkpoint
            config=config,
            version="v2",
        ):
            yield {
                "type": event.get("event"),
                "name": event.get("name"),
                "data": event.get("data", {}),
                "run_id": workflow_run_id,
            }

    async def cancel(self, workflow_run_id: str) -> None:
        """Cancel a running workflow."""
        logger.info("Cancelling workflow | run=%s", workflow_run_id)
        # In a production system, implement workflow cancellation
        # by updating the state to a terminal stage
        await self.initialize()
        config = {"configurable": {"thread_id": workflow_run_id}}
        await self.graph.aupdate_state(
            config,
            {"current_stage": "cancelled"},
        )

    def get_graph_visualization(self) -> str:
        """Get Mermaid diagram of the workflow graph."""
        if self._compiled_graph is None:
            return "Workflow not initialized"
        try:
            return self._compiled_graph.get_graph().draw_mermaid()
        except Exception as e:
            return f"Could not generate diagram: {e}"
