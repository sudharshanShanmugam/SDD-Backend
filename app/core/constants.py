"""Application-wide enums and constants."""
from enum import Enum


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    PROJECT_MANAGER = "project_manager"
    BUSINESS_ANALYST = "business_analyst"
    TECH_LEAD = "tech_lead"
    DEVELOPER = "developer"
    QA_ENGINEER = "qa_engineer"
    STAKEHOLDER = "stakeholder"
    VIEWER = "viewer"


class Permission(str, Enum):
    # Organization
    ORG_CREATE = "org:create"
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    ORG_MANAGE_MEMBERS = "org:manage_members"
    ORG_MANAGE_BILLING = "org:manage_billing"

    # Workspace
    WORKSPACE_CREATE = "workspace:create"
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"
    WORKSPACE_MANAGE_MEMBERS = "workspace:manage_members"

    # Project
    PROJECT_CREATE = "project:create"
    PROJECT_READ = "project:read"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    PROJECT_MANAGE_SETTINGS = "project:manage_settings"
    PROJECT_ARCHIVE = "project:archive"

    # Document
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_READ = "document:read"
    DOCUMENT_UPDATE = "document:update"
    DOCUMENT_DELETE = "document:delete"
    DOCUMENT_PROCESS = "document:process"

    # Requirement
    REQUIREMENT_CREATE = "requirement:create"
    REQUIREMENT_READ = "requirement:read"
    REQUIREMENT_UPDATE = "requirement:update"
    REQUIREMENT_DELETE = "requirement:delete"
    REQUIREMENT_APPROVE = "requirement:approve"

    # Epic
    EPIC_CREATE = "epic:create"
    EPIC_READ = "epic:read"
    EPIC_UPDATE = "epic:update"
    EPIC_DELETE = "epic:delete"

    # User Story
    STORY_CREATE = "story:create"
    STORY_READ = "story:read"
    STORY_UPDATE = "story:update"
    STORY_DELETE = "story:delete"

    # Sprint
    SPRINT_CREATE = "sprint:create"
    SPRINT_READ = "sprint:read"
    SPRINT_UPDATE = "sprint:update"
    SPRINT_DELETE = "sprint:delete"
    SPRINT_MANAGE = "sprint:manage"

    # Task
    TASK_CREATE = "task:create"
    TASK_READ = "task:read"
    TASK_UPDATE = "task:update"
    TASK_DELETE = "task:delete"
    TASK_ASSIGN = "task:assign"

    # AI
    AI_GENERATE = "ai:generate"
    AI_CONFIGURE = "ai:configure"
    AI_VIEW_HISTORY = "ai:view_history"

    # Approval
    APPROVAL_CREATE = "approval:create"
    APPROVAL_REVIEW = "approval:review"
    APPROVAL_OVERRIDE = "approval:override"

    # Audit
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"

    # Admin
    ADMIN_USER_MANAGE = "admin:user_manage"
    ADMIN_SYSTEM_SETTINGS = "admin:system_settings"
    ADMIN_REPORTS = "admin:reports"


# Role -> Permission mapping
ROLE_PERMISSIONS: dict[UserRole, list[Permission]] = {
    UserRole.SUPER_ADMIN: list(Permission),  # All permissions
    UserRole.ORG_ADMIN: [
        Permission.ORG_READ, Permission.ORG_UPDATE, Permission.ORG_MANAGE_MEMBERS,
        Permission.ORG_MANAGE_BILLING,
        Permission.WORKSPACE_CREATE, Permission.WORKSPACE_READ, Permission.WORKSPACE_UPDATE,
        Permission.WORKSPACE_DELETE, Permission.WORKSPACE_MANAGE_MEMBERS,
        Permission.PROJECT_CREATE, Permission.PROJECT_READ, Permission.PROJECT_UPDATE,
        Permission.PROJECT_DELETE, Permission.PROJECT_MANAGE_SETTINGS, Permission.PROJECT_ARCHIVE,
        Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ, Permission.DOCUMENT_UPDATE,
        Permission.DOCUMENT_DELETE, Permission.DOCUMENT_PROCESS,
        Permission.REQUIREMENT_CREATE, Permission.REQUIREMENT_READ, Permission.REQUIREMENT_UPDATE,
        Permission.REQUIREMENT_DELETE, Permission.REQUIREMENT_APPROVE,
        Permission.EPIC_CREATE, Permission.EPIC_READ, Permission.EPIC_UPDATE, Permission.EPIC_DELETE,
        Permission.STORY_CREATE, Permission.STORY_READ, Permission.STORY_UPDATE, Permission.STORY_DELETE,
        Permission.SPRINT_CREATE, Permission.SPRINT_READ, Permission.SPRINT_UPDATE,
        Permission.SPRINT_DELETE, Permission.SPRINT_MANAGE,
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_UPDATE,
        Permission.TASK_DELETE, Permission.TASK_ASSIGN,
        Permission.AI_GENERATE, Permission.AI_CONFIGURE, Permission.AI_VIEW_HISTORY,
        Permission.APPROVAL_CREATE, Permission.APPROVAL_REVIEW, Permission.APPROVAL_OVERRIDE,
        Permission.AUDIT_READ, Permission.AUDIT_EXPORT,
        Permission.ADMIN_USER_MANAGE, Permission.ADMIN_REPORTS,
    ],
    UserRole.PROJECT_MANAGER: [
        Permission.WORKSPACE_READ,
        Permission.PROJECT_CREATE, Permission.PROJECT_READ, Permission.PROJECT_UPDATE,
        Permission.PROJECT_MANAGE_SETTINGS,
        Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ, Permission.DOCUMENT_UPDATE,
        Permission.DOCUMENT_DELETE, Permission.DOCUMENT_PROCESS,
        Permission.REQUIREMENT_CREATE, Permission.REQUIREMENT_READ, Permission.REQUIREMENT_UPDATE,
        Permission.REQUIREMENT_DELETE, Permission.REQUIREMENT_APPROVE,
        Permission.EPIC_CREATE, Permission.EPIC_READ, Permission.EPIC_UPDATE, Permission.EPIC_DELETE,
        Permission.STORY_CREATE, Permission.STORY_READ, Permission.STORY_UPDATE, Permission.STORY_DELETE,
        Permission.SPRINT_CREATE, Permission.SPRINT_READ, Permission.SPRINT_UPDATE,
        Permission.SPRINT_DELETE, Permission.SPRINT_MANAGE,
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_UPDATE,
        Permission.TASK_DELETE, Permission.TASK_ASSIGN,
        Permission.AI_GENERATE, Permission.AI_VIEW_HISTORY,
        Permission.APPROVAL_CREATE, Permission.APPROVAL_REVIEW,
        Permission.AUDIT_READ,
    ],
    UserRole.BUSINESS_ANALYST: [
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ, Permission.DOCUMENT_UPDATE,
        Permission.DOCUMENT_PROCESS,
        Permission.REQUIREMENT_CREATE, Permission.REQUIREMENT_READ, Permission.REQUIREMENT_UPDATE,
        Permission.EPIC_CREATE, Permission.EPIC_READ, Permission.EPIC_UPDATE,
        Permission.STORY_CREATE, Permission.STORY_READ, Permission.STORY_UPDATE,
        Permission.SPRINT_READ,
        Permission.TASK_READ,
        Permission.AI_GENERATE, Permission.AI_VIEW_HISTORY,
        Permission.APPROVAL_CREATE,
        Permission.AUDIT_READ,
    ],
    UserRole.TECH_LEAD: [
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ, Permission.PROJECT_UPDATE,
        Permission.DOCUMENT_READ,
        Permission.REQUIREMENT_READ, Permission.REQUIREMENT_UPDATE,
        Permission.EPIC_READ, Permission.EPIC_UPDATE,
        Permission.STORY_READ, Permission.STORY_UPDATE,
        Permission.SPRINT_CREATE, Permission.SPRINT_READ, Permission.SPRINT_UPDATE, Permission.SPRINT_MANAGE,
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_UPDATE, Permission.TASK_ASSIGN,
        Permission.AI_GENERATE, Permission.AI_VIEW_HISTORY,
        Permission.APPROVAL_REVIEW,
        Permission.AUDIT_READ,
    ],
    UserRole.DEVELOPER: [
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.REQUIREMENT_READ,
        Permission.EPIC_READ,
        Permission.STORY_READ, Permission.STORY_UPDATE,
        Permission.SPRINT_READ,
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_UPDATE,
        Permission.AI_VIEW_HISTORY,
    ],
    UserRole.QA_ENGINEER: [
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.REQUIREMENT_READ,
        Permission.EPIC_READ,
        Permission.STORY_READ,
        Permission.SPRINT_READ,
        Permission.TASK_CREATE, Permission.TASK_READ, Permission.TASK_UPDATE,
        Permission.AI_VIEW_HISTORY,
    ],
    UserRole.STAKEHOLDER: [
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.REQUIREMENT_READ,
        Permission.EPIC_READ,
        Permission.STORY_READ,
        Permission.SPRINT_READ,
        Permission.TASK_READ,
        Permission.APPROVAL_CREATE,
    ],
    UserRole.VIEWER: [
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.REQUIREMENT_READ,
        Permission.EPIC_READ,
        Permission.STORY_READ,
        Permission.SPRINT_READ,
        Permission.TASK_READ,
    ],
}


class WorkflowStage(str, Enum):
    DOCUMENT_UPLOAD = "document_upload"
    REQUIREMENT_EXTRACTION = "requirement_extraction"
    REQUIREMENT_REVIEW = "requirement_review"
    EPIC_GENERATION = "epic_generation"
    EPIC_REVIEW = "epic_review"
    STORY_GENERATION = "story_generation"
    STORY_REVIEW = "story_review"
    SPRINT_PLANNING = "sprint_planning"
    TASK_BREAKDOWN = "task_breakdown"
    QA_GENERATION = "qa_generation"
    RELEASE_PLANNING = "release_planning"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class AIStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"
    CANCELLED = "cancelled"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    ARCHIVED = "archived"


class RequirementType(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    BUSINESS = "business"
    TECHNICAL = "technical"
    CONSTRAINT = "constraint"
    ASSUMPTION = "assumption"


class RequirementPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NICE_TO_HAVE = "nice_to_have"


class StoryStatus(str, Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    TESTING = "testing"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    TESTING = "testing"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    FEATURE = "feature"
    BUG = "bug"
    TECH_DEBT = "tech_debt"
    RESEARCH = "research"
    DOCUMENTATION = "documentation"
    INFRASTRUCTURE = "infrastructure"
    SECURITY = "security"


class SprintStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EpicStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class OrgPlan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class NotificationType(str, Enum):
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_COMPLETED = "approval_completed"
    TASK_ASSIGNED = "task_assigned"
    TASK_UPDATED = "task_updated"
    STORY_UPDATED = "story_updated"
    SPRINT_STARTED = "sprint_started"
    SPRINT_COMPLETED = "sprint_completed"
    AI_GENERATION_COMPLETED = "ai_generation_completed"
    AI_GENERATION_FAILED = "ai_generation_failed"
    MENTION = "mention"
    SYSTEM = "system"


class AuditAction(str, Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    SOFT_DELETE = "soft_delete"
    RESTORE = "restore"
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    PASSWORD_CHANGE = "password_change"
    ROLE_CHANGE = "role_change"
    PERMISSION_CHANGE = "permission_change"
    EXPORT = "export"
    IMPORT = "import"
    AI_GENERATE = "ai_generate"
    APPROVE = "approve"
    REJECT = "reject"


class ReleaseStatus(str, Enum):
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    RELEASED = "released"
    CANCELLED = "cancelled"


class TestCaseStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class TestCaseType(str, Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    FUNCTIONAL = "functional"
    REGRESSION = "regression"
    PERFORMANCE = "performance"
    SECURITY = "security"
    UAT = "uat"


class TestCasePriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Token types
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_RESET_PASSWORD = "reset_password"
TOKEN_TYPE_EMAIL_VERIFY = "email_verify"

# Cache key prefixes
CACHE_KEY_USER = "user:{user_id}"
CACHE_KEY_ORG = "org:{org_id}"
CACHE_KEY_SESSION = "session:{token}"
CACHE_KEY_RATE_LIMIT = "rate_limit:{identifier}:{window}"
CACHE_KEY_AI_JOB = "ai_job:{job_id}"

# Pagination
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# File constraints
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "text/plain",
    "text/markdown",
}
