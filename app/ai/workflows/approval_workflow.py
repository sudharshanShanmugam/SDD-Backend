"""
Approval Checkpoint Workflow

Manages multi-stage approval gates in the SDLC workflow.
Supports auto-approval by confidence threshold, single reviewer,
and multi-stakeholder approval workflows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    HUMAN_APPROVED = "human_approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    TIMED_OUT = "timed_out"


class ApprovalRecord(BaseModel):
    """Record of an approval decision."""
    stage: str
    status: ApprovalStatus
    confidence_score: float
    approver_id: Optional[str] = None
    approver_name: Optional[str] = None
    comments: Optional[str] = None
    requested_changes: List[str] = []
    timestamp: str = ""
    auto_approved: bool = False

    def __init__(self, **data):
        if not data.get("timestamp"):
            data["timestamp"] = datetime.now(timezone.utc).isoformat()
        super().__init__(**data)


class ApprovalGate:
    """
    Manages an approval gate for a specific workflow stage.

    Supports:
    - Auto-approval when confidence exceeds threshold
    - Single reviewer approval
    - Multi-stakeholder approval with quorum
    - Escalation after timeout
    """

    def __init__(
        self,
        stage: str,
        required_approvers: int = 1,
        auto_approve_threshold: float = 0.92,
        timeout_hours: int = 72,
    ):
        self.stage = stage
        self.required_approvers = required_approvers
        self.auto_approve_threshold = auto_approve_threshold
        self.timeout_hours = timeout_hours
        self._approvals: List[ApprovalRecord] = []

    def check_auto_approval(self, confidence_score: float) -> Optional[ApprovalRecord]:
        """
        Check if item can be auto-approved based on confidence.

        Returns ApprovalRecord if auto-approved, None if human review needed.
        """
        if confidence_score >= self.auto_approve_threshold:
            record = ApprovalRecord(
                stage=self.stage,
                status=ApprovalStatus.AUTO_APPROVED,
                confidence_score=confidence_score,
                auto_approved=True,
                comments=f"Auto-approved: confidence {confidence_score:.2f} >= threshold {self.auto_approve_threshold:.2f}",
            )
            self._approvals.append(record)
            logger.info(
                "Auto-approved stage %s (confidence=%.2f)", self.stage, confidence_score
            )
            return record
        return None

    def submit_human_decision(
        self,
        approver_id: str,
        approver_name: str,
        approved: bool,
        comments: str = "",
        requested_changes: Optional[List[str]] = None,
        confidence_score: float = 0.0,
    ) -> ApprovalRecord:
        """Submit a human reviewer's decision."""
        status = ApprovalStatus.HUMAN_APPROVED if approved else ApprovalStatus.REJECTED

        record = ApprovalRecord(
            stage=self.stage,
            status=status,
            confidence_score=confidence_score,
            approver_id=approver_id,
            approver_name=approver_name,
            comments=comments,
            requested_changes=requested_changes or [],
            auto_approved=False,
        )
        self._approvals.append(record)

        logger.info(
            "Human review decision: %s=%s by %s",
            self.stage,
            status.value,
            approver_name,
        )
        return record

    @property
    def is_approved(self) -> bool:
        """Check if this gate has enough approvals."""
        approved_count = sum(
            1 for r in self._approvals
            if r.status in (ApprovalStatus.AUTO_APPROVED, ApprovalStatus.HUMAN_APPROVED)
        )
        rejected_count = sum(
            1 for r in self._approvals
            if r.status == ApprovalStatus.REJECTED
        )

        return approved_count >= self.required_approvers and rejected_count == 0

    @property
    def is_rejected(self) -> bool:
        """Check if any approver has rejected."""
        return any(r.status == ApprovalStatus.REJECTED for r in self._approvals)

    @property
    def pending_approver_count(self) -> int:
        """Count how many more approvals are needed."""
        approved = sum(
            1 for r in self._approvals
            if r.status in (ApprovalStatus.AUTO_APPROVED, ApprovalStatus.HUMAN_APPROVED)
        )
        return max(0, self.required_approvers - approved)

    def get_consolidate_feedback(self) -> Dict[str, Any]:
        """Consolidate all feedback for regeneration."""
        all_changes = []
        all_comments = []

        for r in self._approvals:
            all_changes.extend(r.requested_changes)
            if r.comments:
                all_comments.append(f"{r.approver_name}: {r.comments}")

        return {
            "stage": self.stage,
            "requested_changes": list(set(all_changes)),
            "comments": "\n".join(all_comments),
            "approval_history": [r.model_dump() for r in self._approvals],
        }


class ApprovalWorkflow:
    """
    Manages approval gates across all SDLC workflow stages.

    Tracks approval status for each stage and provides
    consolidated feedback for AI regeneration when rejected.
    """

    # Stages that require human approval (configurable)
    DEFAULT_APPROVAL_STAGES = [
        "requirements",
        "epics",
        "stories",
        "sprint_plan",
    ]

    def __init__(
        self,
        workflow_run_id: str,
        organization_id: str,
        auto_approve_threshold: float = 0.92,
        required_approvers: int = 1,
        timeout_hours: int = 72,
        approval_stages: Optional[List[str]] = None,
    ):
        self.workflow_run_id = workflow_run_id
        self.organization_id = organization_id
        self.auto_approve_threshold = auto_approve_threshold
        self.required_approvers = required_approvers
        self.timeout_hours = timeout_hours
        self.approval_stages = approval_stages or self.DEFAULT_APPROVAL_STAGES

        # Create gates for all configured stages
        self.gates: Dict[str, ApprovalGate] = {
            stage: ApprovalGate(
                stage=stage,
                required_approvers=required_approvers,
                auto_approve_threshold=auto_approve_threshold,
                timeout_hours=timeout_hours,
            )
            for stage in self.approval_stages
        }

    def check_auto_approval(
        self, stage: str, confidence_score: float
    ) -> bool:
        """
        Check if a stage can be auto-approved.
        Returns True if auto-approved, False if human review needed.
        """
        gate = self.gates.get(stage)
        if gate is None:
            # No gate configured for this stage - auto-approve
            return True

        record = gate.check_auto_approval(confidence_score)
        return record is not None

    def submit_approval(
        self,
        stage: str,
        approver_id: str,
        approver_name: str,
        approved: bool,
        comments: str = "",
        requested_changes: Optional[List[str]] = None,
        confidence_score: float = 0.0,
    ) -> ApprovalRecord:
        """Submit a human approval decision for a stage."""
        gate = self.gates.get(stage)
        if gate is None:
            raise ValueError(f"No approval gate configured for stage: {stage}")

        return gate.submit_human_decision(
            approver_id=approver_id,
            approver_name=approver_name,
            approved=approved,
            comments=comments,
            requested_changes=requested_changes,
            confidence_score=confidence_score,
        )

    def get_stage_status(self, stage: str) -> ApprovalStatus:
        """Get the current approval status for a stage."""
        gate = self.gates.get(stage)
        if gate is None:
            return ApprovalStatus.AUTO_APPROVED

        if gate.is_rejected:
            return ApprovalStatus.REJECTED
        if gate.is_approved:
            return ApprovalStatus.HUMAN_APPROVED
        return ApprovalStatus.PENDING

    def get_pending_stages(self) -> List[str]:
        """Get list of stages still awaiting approval."""
        return [
            stage for stage in self.approval_stages
            if self.get_stage_status(stage) == ApprovalStatus.PENDING
        ]

    def is_workflow_approved(self) -> bool:
        """Check if all configured stages have been approved."""
        return all(
            self.get_stage_status(stage) in (
                ApprovalStatus.HUMAN_APPROVED,
                ApprovalStatus.AUTO_APPROVED,
            )
            for stage in self.approval_stages
        )

    def get_rejection_feedback(self, stage: str) -> Optional[Dict[str, Any]]:
        """Get consolidated rejection feedback for a stage."""
        gate = self.gates.get(stage)
        if gate and gate.is_rejected:
            return gate.get_consolidate_feedback()
        return None

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all approval decisions."""
        return {
            "workflow_run_id": self.workflow_run_id,
            "total_stages": len(self.approval_stages),
            "approved_stages": sum(
                1 for s in self.approval_stages
                if self.get_stage_status(s) in (
                    ApprovalStatus.HUMAN_APPROVED, ApprovalStatus.AUTO_APPROVED
                )
            ),
            "pending_stages": self.get_pending_stages(),
            "all_approved": self.is_workflow_approved(),
            "stage_statuses": {
                stage: self.get_stage_status(stage).value
                for stage in self.approval_stages
            },
        }
