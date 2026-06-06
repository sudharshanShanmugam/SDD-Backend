"""
WebSocket event type definitions.
All event names, payload schemas, and routing constants for the SDD platform.
"""
from enum import Enum
from typing import Any, Literal


class EventType(str, Enum):
    """All WebSocket event type constants."""

    # ── Document events ────────────────────────────────────────────────────
    DOCUMENT_PROCESSING_STARTED = "document.processing.started"
    DOCUMENT_PROCESSING_PROGRESS = "document.processing.progress"
    DOCUMENT_PROCESSING_COMPLETED = "document.processing.completed"
    DOCUMENT_PROCESSING_FAILED = "document.processing.failed"

    # ── AI generation events ───────────────────────────────────────────────
    AI_GENERATION_STARTED = "ai.generation.started"
    AI_GENERATION_PROGRESS = "ai.generation.progress"
    AI_GENERATION_COMPLETED = "ai.generation.completed"
    AI_GENERATION_FAILED = "ai.generation.failed"

    # ── Approval events ────────────────────────────────────────────────────
    APPROVAL_CREATED = "approval.created"
    APPROVAL_UPDATED = "approval.updated"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_CHANGES_REQUESTED = "approval.changes_requested"
    APPROVAL_COMMENTED = "approval.commented"

    # ── Workflow events ────────────────────────────────────────────────────
    WORKFLOW_STAGE_CHANGED = "workflow.stage.changed"
    WORKFLOW_STAGE_TRANSITION_FAILED = "workflow.stage.transition_failed"

    # ── Notification events ────────────────────────────────────────────────
    NOTIFICATION_NEW = "notification.new"
    NOTIFICATION_READ = "notification.read"
    NOTIFICATION_ALL_READ = "notification.all_read"

    # ── Presence events ────────────────────────────────────────────────────
    PRESENCE_JOIN = "presence.join"
    PRESENCE_LEAVE = "presence.leave"
    PRESENCE_UPDATE = "presence.update"
    PRESENCE_LIST = "presence.list"

    # ── Collaboration events ───────────────────────────────────────────────
    COLLABORATION_CURSOR = "collaboration.cursor"
    COLLABORATION_EDIT = "collaboration.edit"
    COLLABORATION_LOCK = "collaboration.lock"
    COLLABORATION_UNLOCK = "collaboration.unlock"
    COLLABORATION_SELECTION = "collaboration.selection"

    # ── Sprint / project events ────────────────────────────────────────────
    SPRINT_STARTED = "sprint.started"
    SPRINT_COMPLETED = "sprint.completed"
    STORY_STATUS_CHANGED = "story.status_changed"
    TASK_STATUS_CHANGED = "task.status_changed"
    TASK_ASSIGNED = "task.assigned"

    # ── System events ──────────────────────────────────────────────────────
    SYSTEM_ANNOUNCEMENT = "system.announcement"
    SYSTEM_MAINTENANCE = "system.maintenance"

    # ── Connection management ──────────────────────────────────────────────
    CONNECTION_ESTABLISHED = "connection.established"
    CONNECTION_PING = "connection.ping"
    CONNECTION_PONG = "connection.pong"
    CONNECTION_ERROR = "connection.error"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


# ── Event payload types ────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BaseEvent:
    """Base event wrapper sent over WebSocket."""
    event: str
    data: dict
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "data": self.data,
            "timestamp": self.timestamp,
            "version": self.version,
        }


@dataclass
class DocumentProcessingEvent(BaseEvent):
    """Document processing lifecycle event."""

    @classmethod
    def started(cls, document_id: str, project_id: str | None = None) -> "DocumentProcessingEvent":
        return cls(
            event=EventType.DOCUMENT_PROCESSING_STARTED,
            data={"document_id": document_id, "project_id": project_id},
        )

    @classmethod
    def progress(cls, document_id: str, progress: int, step: str) -> "DocumentProcessingEvent":
        return cls(
            event=EventType.DOCUMENT_PROCESSING_PROGRESS,
            data={"document_id": document_id, "progress": progress, "step": step},
        )

    @classmethod
    def completed(cls, document_id: str, chunk_count: int, page_count: int | None) -> "DocumentProcessingEvent":
        return cls(
            event=EventType.DOCUMENT_PROCESSING_COMPLETED,
            data={
                "document_id": document_id,
                "chunk_count": chunk_count,
                "page_count": page_count,
            },
        )

    @classmethod
    def failed(cls, document_id: str, error: str) -> "DocumentProcessingEvent":
        return cls(
            event=EventType.DOCUMENT_PROCESSING_FAILED,
            data={"document_id": document_id, "error": error},
        )


@dataclass
class AIGenerationEvent(BaseEvent):
    """AI workflow generation lifecycle event."""

    @classmethod
    def started(cls, run_id: str, workflow_type: str, **kwargs) -> "AIGenerationEvent":
        return cls(
            event=EventType.AI_GENERATION_STARTED,
            data={"run_id": run_id, "workflow_type": workflow_type, **kwargs},
        )

    @classmethod
    def progress(cls, run_id: str, progress: int, step: str, workflow_type: str) -> "AIGenerationEvent":
        return cls(
            event=EventType.AI_GENERATION_PROGRESS,
            data={"run_id": run_id, "progress": progress, "step": step, "workflow_type": workflow_type},
        )

    @classmethod
    def completed(cls, run_id: str, workflow_type: str, result: dict) -> "AIGenerationEvent":
        return cls(
            event=EventType.AI_GENERATION_COMPLETED,
            data={"run_id": run_id, "workflow_type": workflow_type, "result": result},
        )

    @classmethod
    def failed(cls, run_id: str, workflow_type: str, error: str) -> "AIGenerationEvent":
        return cls(
            event=EventType.AI_GENERATION_FAILED,
            data={"run_id": run_id, "workflow_type": workflow_type, "error": error},
        )


@dataclass
class ApprovalEvent(BaseEvent):
    """Approval workflow event."""

    @classmethod
    def created(cls, approval_id: str, entity_type: str, entity_title: str) -> "ApprovalEvent":
        return cls(
            event=EventType.APPROVAL_CREATED,
            data={"approval_id": approval_id, "entity_type": entity_type, "entity_title": entity_title},
        )

    @classmethod
    def updated(cls, approval_id: str, status: str, reviewer_id: str) -> "ApprovalEvent":
        return cls(
            event=EventType.APPROVAL_UPDATED,
            data={"approval_id": approval_id, "status": status, "reviewer_id": reviewer_id},
        )


@dataclass
class PresenceEvent(BaseEvent):
    """User presence event."""

    @classmethod
    def join(cls, user_id: str, room_id: str, user_name: str) -> "PresenceEvent":
        return cls(
            event=EventType.PRESENCE_JOIN,
            data={"user_id": user_id, "room_id": room_id, "user_name": user_name},
        )

    @classmethod
    def leave(cls, user_id: str, room_id: str) -> "PresenceEvent":
        return cls(
            event=EventType.PRESENCE_LEAVE,
            data={"user_id": user_id, "room_id": room_id},
        )

    @classmethod
    def list_users(cls, room_id: str, users: list) -> "PresenceEvent":
        return cls(
            event=EventType.PRESENCE_LIST,
            data={"room_id": room_id, "users": users},
        )


@dataclass
class CollaborationEvent(BaseEvent):
    """Real-time collaboration event (cursor, edit, lock)."""

    @classmethod
    def cursor(cls, user_id: str, entity_id: str, position: dict) -> "CollaborationEvent":
        return cls(
            event=EventType.COLLABORATION_CURSOR,
            data={"user_id": user_id, "entity_id": entity_id, "position": position},
        )

    @classmethod
    def edit(cls, user_id: str, entity_id: str, field: str, value: Any, version: int) -> "CollaborationEvent":
        return cls(
            event=EventType.COLLABORATION_EDIT,
            data={
                "user_id": user_id,
                "entity_id": entity_id,
                "field": field,
                "value": value,
                "version": version,
            },
        )

    @classmethod
    def lock(cls, user_id: str, entity_id: str) -> "CollaborationEvent":
        return cls(
            event=EventType.COLLABORATION_LOCK,
            data={"user_id": user_id, "entity_id": entity_id},
        )

    @classmethod
    def unlock(cls, entity_id: str) -> "CollaborationEvent":
        return cls(
            event=EventType.COLLABORATION_UNLOCK,
            data={"entity_id": entity_id},
        )


@dataclass
class WorkflowEvent(BaseEvent):
    """Project workflow stage change event."""

    @classmethod
    def stage_changed(
        cls,
        project_id: str,
        from_stage: str,
        to_stage: str,
        changed_by: str,
    ) -> "WorkflowEvent":
        return cls(
            event=EventType.WORKFLOW_STAGE_CHANGED,
            data={
                "project_id": project_id,
                "from_stage": from_stage,
                "to_stage": to_stage,
                "changed_by": changed_by,
            },
        )


# ── Room name builders ─────────────────────────────────────────────────────────

def project_room(project_id: str) -> str:
    return f"project:{project_id}"


def user_room(user_id: str) -> str:
    return f"user:{user_id}"


def org_room(org_id: str) -> str:
    return f"org:{org_id}"


def workspace_room(workspace_id: str) -> str:
    return f"workspace:{workspace_id}"


def entity_room(entity_type: str, entity_id: str) -> str:
    return f"entity:{entity_type}:{entity_id}"


# ── Subscription topics (for client-side subscribe messages) ───────────────────

SUBSCRIBABLE_TOPICS = {
    "project": "Subscribe to all events in a project room",
    "user": "Subscribe to personal notifications",
    "org": "Subscribe to organization-wide broadcasts",
    "workspace": "Subscribe to workspace events",
    "entity": "Subscribe to a specific entity's collaboration events",
}
