"""
LangGraph Node Implementations

Each function in this module is a node in the SDLC workflow graph.
Nodes receive the current state, perform AI operations, and return state updates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.ai.agents.api_spec_generator import APISpecGeneratorAgent
from app.ai.agents.dependency_analyzer import DependencyAnalyzerAgent
from app.ai.agents.documentation_agent import DocumentationAgent
from app.ai.agents.epic_generator import EpicGeneratorAgent
from app.ai.agents.estimation_agent import EstimationAgent
from app.ai.agents.qa_generator import QAGeneratorAgent
from app.ai.agents.release_notes_agent import ReleaseNotesAgent
from app.ai.agents.requirement_extractor import RequirementExtractorAgent
from app.ai.agents.requirement_structurer import RequirementStructurerAgent
from app.ai.agents.risk_detector import RiskDetectorAgent
from app.ai.agents.sprint_planner import SprintPlannerAgent
from app.ai.agents.story_generator import StoryGeneratorAgent
from app.ai.agents.task_breakdown import TaskBreakdownAgent
from app.ai.agents.traceability_agent import TraceabilityAgent
from app.ai.agents.ui_spec_generator import UISpecGeneratorAgent
from app.ai.workflows.state import SDLCWorkflowState, WorkflowError

logger = logging.getLogger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _record_error(
    state: SDLCWorkflowState,
    stage: str,
    error_type: str,
    message: str,
) -> List[WorkflowError]:
    """Create error record and append to existing errors."""
    error: WorkflowError = {
        "stage": stage,
        "error_type": error_type,
        "message": message,
        "timestamp": _now(),
        "retry_count": state.get("retry_count", 0),
    }
    return state.get("errors", []) + [error]


def _accumulate_tokens(state: SDLCWorkflowState, tokens: int) -> int:
    """Add tokens to running total."""
    return state.get("total_tokens_used", 0) + tokens


def _update_confidence(
    state: SDLCWorkflowState,
    stage: str,
    scores: Dict[str, float],
) -> Dict[str, float]:
    """Merge new confidence scores into state."""
    current = dict(state.get("confidence_scores", {}))
    current[stage] = scores.get("overall", 0.0)
    current[f"{stage}_detail"] = scores
    return current


# ── Document Processing Node ─────────────────────────────────────────────────

async def chunk_document_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """
    Split the document into chunks for processing.
    Uses the RAG chunker for intelligent segmentation.
    """
    logger.info("Node: chunk_document | run=%s", state["workflow_run_id"])

    try:
        from app.ai.rag.chunker import DocumentChunker

        chunker = DocumentChunker()
        chunks = await chunker.chunk_document(
            content=state["document_content"],
            metadata={
                "document_id": state["document_id"],
                "project_id": state["project_id"],
                "organization_id": state["organization_id"],
            },
        )

        logger.info("Document split into %d chunks", len(chunks))

        return {
            "document_chunks": [
                {"content": c.page_content, "metadata": c.metadata}
                for c in chunks
            ],
            "current_stage": "document_chunked",
            "completed_stages": state.get("completed_stages", []) + ["chunk_document"],
        }
    except Exception as e:
        logger.exception("chunk_document_node failed: %s", e)
        return {
            "errors": _record_error(state, "chunk_document", type(e).__name__, str(e)),
            "document_chunks": [],
            "current_stage": "error",
        }


# ── Extraction Nodes ─────────────────────────────────────────────────────────

async def extract_requirements_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """
    Extract raw requirements from document chunks using AI.
    """
    logger.info("Node: extract_requirements | run=%s", state["workflow_run_id"])

    try:
        agent = RequirementExtractorAgent()
        config = state.get("workflow_config", {})

        # Use chunked extraction for large documents
        chunks = state.get("document_chunks", [])
        if chunks and len(chunks) > 1:
            chunk_texts = [c.get("content", "") for c in chunks]
            result = await agent.extract_from_chunks(
                document_chunks=chunk_texts,
                project_type=config.get("project_type", "web_application"),
                domain=config.get("domain", "general"),
                organization_id=state["organization_id"],
            )
        else:
            result = await agent.extract(
                document_content=state["document_content"],
                project_type=config.get("project_type", "web_application"),
                domain=config.get("domain", "general"),
                organization_id=state["organization_id"],
            )

        if not result.success:
            return {
                "errors": _record_error(
                    state, "extract_requirements", "AgentError", result.error or "Unknown"
                ),
                "current_stage": "error",
            }

        extraction = result.data

        # Flatten all requirements into a single list for convenience
        all_requirements = (
            extraction.functional_requirements
            + extraction.non_functional_requirements
            + extraction.constraints
            + extraction.assumptions
        )

        return {
            "raw_requirements": all_requirements,
            "ambiguous_requirements": extraction.ambiguous_items,
            "total_tokens_used": _accumulate_tokens(state, result.tokens_used),
            "confidence_scores": _update_confidence(
                state, "extraction", result.confidence_scores
            ),
            "current_stage": "requirements_extracted",
            "completed_stages": state.get("completed_stages", []) + ["extract_requirements"],
        }
    except Exception as e:
        logger.exception("extract_requirements_node failed: %s", e)
        return {
            "errors": _record_error(state, "extract_requirements", type(e).__name__, str(e)),
            "current_stage": "error",
        }


async def validate_requirements_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """
    Validate that extracted requirements meet minimum quality standards.
    """
    logger.info("Node: validate_requirements | run=%s", state["workflow_run_id"])

    requirements = state.get("raw_requirements", [])

    validation_errors = []
    if not requirements:
        validation_errors.append("No requirements extracted from document")

    # Check minimum counts
    functional = [r for r in requirements if r.get("id", "").startswith("FR-")]
    if len(functional) == 0:
        validation_errors.append("No functional requirements found")

    # Flag ambiguous requirements
    ambiguous = state.get("ambiguous_requirements", [])
    if len(ambiguous) > len(requirements) * 0.3:
        validation_errors.append(
            f"High ambiguity: {len(ambiguous)} of {len(requirements)} items are ambiguous"
        )

    if validation_errors:
        logger.warning(
            "Requirement validation issues: %s", validation_errors
        )
        return {
            "errors": _record_error(
                state,
                "validate_requirements",
                "ValidationError",
                "; ".join(validation_errors),
            ),
            "current_stage": "validation_failed",
        }

    return {
        "current_stage": "requirements_validated",
        "completed_stages": state.get("completed_stages", []) + ["validate_requirements"],
    }


async def structure_requirements_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """
    Structure and categorize raw requirements into domains and priorities.
    """
    logger.info("Node: structure_requirements | run=%s", state["workflow_run_id"])

    try:
        agent = RequirementStructurerAgent()

        # Build raw requirements dict from state
        raw_req_dict = {
            "functional_requirements": [
                r for r in state.get("raw_requirements", [])
                if r.get("id", "").startswith("FR-")
            ],
            "non_functional_requirements": [
                r for r in state.get("raw_requirements", [])
                if r.get("id", "").startswith("NFR-")
            ],
            "constraints": [
                r for r in state.get("raw_requirements", [])
                if r.get("id", "").startswith("CON-")
            ],
            "assumptions": [
                r for r in state.get("raw_requirements", [])
                if r.get("id", "").startswith("ASM-")
            ],
        }

        result = await agent.structure(
            raw_requirements=raw_req_dict,
            organization_id=state["organization_id"],
        )

        if not result.success:
            return {
                "errors": _record_error(
                    state, "structure_requirements", "AgentError", result.error or "Unknown"
                ),
                "current_stage": "error",
            }

        structuring = result.data

        return {
            "structured_requirements": structuring.structured_requirements,
            "requirement_domains": structuring.domains,
            "requirement_conflicts": structuring.conflicts,
            "missing_requirements": structuring.missing_requirements,
            "total_tokens_used": _accumulate_tokens(state, result.tokens_used),
            "confidence_scores": _update_confidence(
                state, "structuring", result.confidence_scores
            ),
            "current_stage": "requirements_structured",
            "completed_stages": state.get("completed_stages", []) + ["structure_requirements"],
        }
    except Exception as e:
        logger.exception("structure_requirements_node failed: %s", e)
        return {
            "errors": _record_error(state, "structure_requirements", type(e).__name__, str(e)),
            "current_stage": "error",
        }


# ── Human Approval Nodes ─────────────────────────────────────────────────────

async def await_requirements_approval_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """
    Human interrupt node: pause workflow for requirements review.
    LangGraph will interrupt here when interrupt_before is configured.
    """
    logger.info(
        "Node: await_requirements_approval | run=%s | AWAITING HUMAN REVIEW",
        state["workflow_run_id"],
    )
    return {
        "awaiting_approval": True,
        "approval_stage": "requirements",
        "current_stage": "awaiting_requirements_approval",
    }


async def await_epics_approval_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Human interrupt node: pause workflow for epic review."""
    logger.info(
        "Node: await_epics_approval | run=%s | AWAITING HUMAN REVIEW",
        state["workflow_run_id"],
    )
    return {
        "awaiting_approval": True,
        "approval_stage": "epics",
        "current_stage": "awaiting_epics_approval",
    }


async def await_stories_approval_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Human interrupt node: pause workflow for stories review."""
    logger.info(
        "Node: await_stories_approval | run=%s | AWAITING HUMAN REVIEW",
        state["workflow_run_id"],
    )
    return {
        "awaiting_approval": True,
        "approval_stage": "stories",
        "current_stage": "awaiting_stories_approval",
    }


# ── Epic Node ─────────────────────────────────────────────────────────────────

async def generate_epics_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Generate epics from structured requirements."""
    logger.info("Node: generate_epics | run=%s", state["workflow_run_id"])

    try:
        agent = EpicGeneratorAgent()
        config = state.get("workflow_config", {})

        # Build structured requirements for the agent
        structured_req_input = {
            "structured_requirements": state.get("structured_requirements", []),
            "domains": state.get("requirement_domains", []),
        }

        result = await agent.generate(
            structured_requirements=structured_req_input,
            project_name=config.get("project_name", "Project"),
            team_size=config.get("team_size", 5),
            sprint_length_weeks=config.get("sprint_length_weeks", 2),
            domain=config.get("domain", "general"),
            target_users=config.get("target_users", "end users"),
            organization_id=state["organization_id"],
        )

        if not result.success:
            return {
                "errors": _record_error(
                    state, "generate_epics", "AgentError", result.error or "Unknown"
                ),
                "current_stage": "error",
            }

        epic_result = result.data

        return {
            "epics": epic_result.epics,
            "epic_coverage_gaps": epic_result.coverage_gaps,
            "total_estimated_sprints": epic_result.total_estimated_sprints,
            "total_tokens_used": _accumulate_tokens(state, result.tokens_used),
            "confidence_scores": _update_confidence(
                state, "epics", result.confidence_scores
            ),
            "current_stage": "epics_generated",
            "completed_stages": state.get("completed_stages", []) + ["generate_epics"],
        }
    except Exception as e:
        logger.exception("generate_epics_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_epics", type(e).__name__, str(e)),
            "current_stage": "error",
        }


# ── Story Node ────────────────────────────────────────────────────────────────

async def generate_stories_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Generate user stories for all approved epics."""
    logger.info("Node: generate_stories | run=%s", state["workflow_run_id"])

    try:
        agent = StoryGeneratorAgent()
        config = state.get("workflow_config", {})
        epics = state.get("epics", [])
        requirements = state.get("structured_requirements", [])

        if not epics:
            return {
                "errors": _record_error(
                    state, "generate_stories", "ValidationError", "No epics to generate stories for"
                ),
                "current_stage": "error",
            }

        # Generate stories for all epics
        results = await agent.generate_for_all_epics(
            epics=epics,
            requirements=requirements,
            sprint_velocity=config.get("sprint_velocity", 40),
            sprint_length_weeks=config.get("sprint_length_weeks", 2),
            organization_id=state["organization_id"],
        )

        # Collect all stories
        all_stories = []
        all_invest_violations = []
        total_tokens = 0

        for epic_id, result in results.items():
            if result.success and result.data:
                all_stories.extend(result.data.stories)
                all_invest_violations.extend(
                    result.data.invest_analysis.get("issues", [])
                )
                total_tokens += result.tokens_used

        return {
            "user_stories": all_stories,
            "invest_violations": all_invest_violations,
            "total_tokens_used": _accumulate_tokens(state, total_tokens),
            "current_stage": "stories_generated",
            "completed_stages": state.get("completed_stages", []) + ["generate_stories"],
        }
    except Exception as e:
        logger.exception("generate_stories_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_stories", type(e).__name__, str(e)),
            "current_stage": "error",
        }


# ── Sprint Planning Node ──────────────────────────────────────────────────────

async def generate_sprint_plan_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Generate sprint plan from stories."""
    logger.info("Node: generate_sprint_plan | run=%s", state["workflow_run_id"])

    try:
        agent = SprintPlannerAgent()
        config = state.get("workflow_config", {})

        result = await agent.plan(
            stories=state.get("user_stories", []),
            team_size=config.get("team_size", 5),
            sprint_length_weeks=config.get("sprint_length_weeks", 2),
            sprint_velocity=config.get("sprint_velocity", 40),
            num_sprints=config.get("num_sprints", 6),
            organization_id=state["organization_id"],
        )

        if not result.success:
            return {
                "errors": _record_error(
                    state, "generate_sprint_plan", "AgentError", result.error or "Unknown"
                ),
                "current_stage": "error",
            }

        return {
            "sprint_plan": result.data.sprint_plan,
            "total_tokens_used": _accumulate_tokens(state, result.tokens_used),
            "confidence_scores": _update_confidence(
                state, "sprint_plan", result.confidence_scores
            ),
            "current_stage": "sprint_plan_generated",
            "completed_stages": state.get("completed_stages", []) + ["generate_sprint_plan"],
        }
    except Exception as e:
        logger.exception("generate_sprint_plan_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_sprint_plan", type(e).__name__, str(e)),
            "current_stage": "error",
        }


# ── Task Node ─────────────────────────────────────────────────────────────────

async def generate_tasks_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Break all stories into engineering tasks."""
    logger.info("Node: generate_tasks | run=%s", state["workflow_run_id"])

    try:
        agent = TaskBreakdownAgent()
        config = state.get("workflow_config", {})
        stories = state.get("user_stories", [])

        all_tasks = []
        total_tokens = 0

        # Process stories in batches to manage concurrency
        import asyncio

        async def breakdown_story(story: Dict) -> List[Dict]:
            result = await agent.breakdown(
                story=story,
                tech_stack=config.get("tech_stack"),
                architecture=config.get("architecture", "monolith"),
                database_type=config.get("database_type", "PostgreSQL"),
                frontend_framework=config.get("frontend_framework", "React"),
                organization_id=state["organization_id"],
            )
            if result.success and result.data:
                return result.data.tasks, result.tokens_used
            return [], 0

        tasks_results = await asyncio.gather(
            *[breakdown_story(s) for s in stories[:20]],  # Limit to first 20
            return_exceptions=True,
        )

        for result in tasks_results:
            if isinstance(result, Exception):
                logger.error("Task breakdown failed: %s", result)
            else:
                tasks, tokens = result
                all_tasks.extend(tasks)
                total_tokens += tokens

        # Create summary
        task_summary = {
            "total_tasks": len(all_tasks),
            "total_hours": sum(t.get("estimated_hours", 0) for t in all_tasks),
            "by_category": {},
        }
        for task in all_tasks:
            cat = task.get("category", "OTHER")
            task_summary["by_category"][cat] = (
                task_summary["by_category"].get(cat, 0) + task.get("estimated_hours", 0)
            )

        return {
            "tasks": all_tasks,
            "task_summary": task_summary,
            "total_tokens_used": _accumulate_tokens(state, total_tokens),
            "current_stage": "tasks_generated",
            "completed_stages": state.get("completed_stages", []) + ["generate_tasks"],
        }
    except Exception as e:
        logger.exception("generate_tasks_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_tasks", type(e).__name__, str(e)),
            "current_stage": "error",
        }


# ── Parallel Spec Nodes ───────────────────────────────────────────────────────

async def generate_ui_spec_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Generate UI specifications (runs in parallel with API spec)."""
    logger.info("Node: generate_ui_spec | run=%s", state["workflow_run_id"])

    try:
        agent = UISpecGeneratorAgent()
        config = state.get("workflow_config", {})

        result = await agent.generate(
            stories=state.get("user_stories", [])[:10],  # Sample for spec gen
            component_library=config.get("component_library", "shadcn/ui"),
            organization_id=state["organization_id"],
        )

        if not result.success:
            logger.warning("UI spec generation failed: %s", result.error)
            return {"ui_spec": {}, "current_stage": state.get("current_stage", "")}

        return {
            "ui_spec": result.data.ui_spec,
            "total_tokens_used": _accumulate_tokens(state, result.tokens_used),
        }
    except Exception as e:
        logger.exception("generate_ui_spec_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_ui_spec", type(e).__name__, str(e)),
            "ui_spec": {},
        }


async def generate_api_spec_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Generate API specifications (runs in parallel with UI spec)."""
    logger.info("Node: generate_api_spec | run=%s", state["workflow_run_id"])

    try:
        agent = APISpecGeneratorAgent()
        config = state.get("workflow_config", {})

        result = await agent.generate(
            stories=state.get("user_stories", [])[:10],
            base_url=config.get("api_base_url", "https://api.example.com"),
            api_version=config.get("api_version", "v1"),
            organization_id=state["organization_id"],
        )

        if not result.success:
            logger.warning("API spec generation failed: %s", result.error)
            return {"api_spec": {}, "current_stage": state.get("current_stage", "")}

        return {
            "api_spec": result.data.spec,
            "total_tokens_used": _accumulate_tokens(state, result.tokens_used),
        }
    except Exception as e:
        logger.exception("generate_api_spec_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_api_spec", type(e).__name__, str(e)),
            "api_spec": {},
        }


# ── QA Node ───────────────────────────────────────────────────────────────────

async def generate_qa_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Generate QA test suites for all stories."""
    logger.info("Node: generate_qa | run=%s", state["workflow_run_id"])

    try:
        agent = QAGeneratorAgent()
        config = state.get("workflow_config", {})

        # Generate tests for stories (limit to manageable batch)
        stories = state.get("user_stories", [])[:15]

        results = await agent.generate_regression_suite(
            stories=stories,
            organization_id=state["organization_id"],
        )

        test_suites = []
        total_tokens = 0

        for story_id, result in results.items():
            if result.success and result.data:
                test_suites.append(result.data.test_suite)
                total_tokens += result.tokens_used

        return {
            "qa_test_suites": test_suites,
            "total_tokens_used": _accumulate_tokens(state, total_tokens),
            "current_stage": "qa_generated",
            "completed_stages": state.get("completed_stages", []) + ["generate_qa"],
        }
    except Exception as e:
        logger.exception("generate_qa_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_qa", type(e).__name__, str(e)),
            "qa_test_suites": [],
            "current_stage": "error",
        }


# ── Documentation Node ────────────────────────────────────────────────────────

async def generate_documentation_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Generate technical documentation."""
    logger.info("Node: generate_documentation | run=%s", state["workflow_run_id"])

    try:
        agent = DocumentationAgent()
        config = state.get("workflow_config", {})

        result = await agent.generate(
            doc_type="architecture",
            doc_title=f"{config.get('project_name', 'Project')} - Technical Documentation",
            epics=state.get("epics", []),
            stories=state.get("user_stories", [])[:5],
            api_spec=state.get("api_spec"),
            organization_id=state["organization_id"],
        )

        if not result.success:
            logger.warning("Documentation generation failed: %s", result.error)
            return {"documentation": {}}

        return {
            "documentation": result.data.documentation,
            "total_tokens_used": _accumulate_tokens(state, result.tokens_used),
            "current_stage": "documentation_generated",
            "completed_stages": state.get("completed_stages", []) + ["generate_documentation"],
        }
    except Exception as e:
        logger.exception("generate_documentation_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_documentation", type(e).__name__, str(e)),
            "documentation": {},
        }


# ── Release Notes Node ────────────────────────────────────────────────────────

async def generate_release_notes_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Generate release notes for the sprint/release."""
    logger.info("Node: generate_release_notes | run=%s", state["workflow_run_id"])

    try:
        agent = ReleaseNotesAgent()
        config = state.get("workflow_config", {})

        result = await agent.generate(
            version=config.get("release_version", "1.0.0"),
            release_date=config.get("release_date", "TBD"),
            completed_stories=state.get("user_stories", []),
            completed_epics=state.get("epics", []),
            organization_id=state["organization_id"],
        )

        if not result.success:
            return {"release_notes": {}}

        return {
            "release_notes": result.data.release_notes,
            "total_tokens_used": _accumulate_tokens(state, result.tokens_used),
            "current_stage": "release_notes_generated",
            "completed_stages": state.get("completed_stages", []) + ["generate_release_notes"],
        }
    except Exception as e:
        logger.exception("generate_release_notes_node failed: %s", e)
        return {
            "errors": _record_error(state, "generate_release_notes", type(e).__name__, str(e)),
            "release_notes": {},
        }


# ── Finalization Node ─────────────────────────────────────────────────────────

async def finalize_workflow_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """Mark workflow as complete and compute final metrics."""
    logger.info("Node: finalize_workflow | run=%s", state["workflow_run_id"])

    # Compute cost estimate
    total_tokens = state.get("total_tokens_used", 0)
    # Approximate: assume 70% input, 30% output at GPT-4o rates
    input_cost = (total_tokens * 0.7 / 1000) * 0.0025
    output_cost = (total_tokens * 0.3 / 1000) * 0.010
    total_cost = round(input_cost + output_cost, 4)

    completed_stages = state.get("completed_stages", [])
    logger.info(
        "Workflow complete | run=%s | stages=%d | tokens=%d | cost=$%.4f",
        state["workflow_run_id"],
        len(completed_stages),
        total_tokens,
        total_cost,
    )

    return {
        "current_stage": "completed",
        "total_cost_usd": total_cost,
        "completed_stages": completed_stages + ["finalize_workflow"],
        "awaiting_approval": False,
    }


# ── Error Recovery Node ───────────────────────────────────────────────────────

async def handle_error_node(state: SDLCWorkflowState) -> Dict[str, Any]:
    """
    Handle errors and determine if retry is possible.
    """
    errors = state.get("errors", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    logger.error(
        "handle_error_node | run=%s | errors=%d | retry=%d/%d",
        state["workflow_run_id"],
        len(errors),
        retry_count,
        max_retries,
    )

    if retry_count < max_retries and errors:
        last_error = errors[-1]
        logger.info(
            "Retrying from stage: %s (attempt %d/%d)",
            last_error.get("stage"),
            retry_count + 1,
            max_retries,
        )
        return {
            "retry_count": retry_count + 1,
            "current_stage": f"retry_{last_error.get('stage', 'unknown')}",
        }

    logger.error(
        "Workflow failed permanently after %d retries | run=%s",
        retry_count,
        state["workflow_run_id"],
    )
    return {
        "current_stage": "failed",
        "retry_count": retry_count,
    }
