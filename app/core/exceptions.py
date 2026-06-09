"""Custom exception hierarchy for the SDD platform."""
from typing import Any, Optional


class SDDBaseException(Exception):
    """Root exception for all SDD platform errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred"

    def __init__(
        self,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        detail: Optional[Any] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.error_code = error_code or self.__class__.error_code
        self.detail = detail
        self.headers = headers
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.detail is not None:
            result["detail"] = self.detail
        return result


# ── Authentication / Authorization ────────────────────────────────────────────

class AuthenticationError(SDDBaseException):
    status_code = 401
    error_code = "AUTHENTICATION_FAILED"
    message = "Authentication failed"


class InvalidCredentialsError(AuthenticationError):
    error_code = "INVALID_CREDENTIALS"
    message = "Invalid email or password"


class TokenExpiredError(AuthenticationError):
    error_code = "TOKEN_EXPIRED"
    message = "Access token has expired"


class InvalidTokenError(AuthenticationError):
    error_code = "INVALID_TOKEN"
    message = "Invalid or malformed token"


class TokenRevokedError(AuthenticationError):
    error_code = "TOKEN_REVOKED"
    message = "Token has been revoked"


class EmailNotVerifiedError(AuthenticationError):
    error_code = "EMAIL_NOT_VERIFIED"
    message = "Email address has not been verified"


class AccountDisabledError(AuthenticationError):
    error_code = "ACCOUNT_DISABLED"
    message = "Account has been disabled"


class PermissionDeniedError(SDDBaseException):
    status_code = 403
    error_code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action"


class InsufficientRoleError(PermissionDeniedError):
    error_code = "INSUFFICIENT_ROLE"
    message = "Your role does not have the required permissions"


# ── Resource errors ───────────────────────────────────────────────────────────

class NotFoundError(SDDBaseException):
    status_code = 404
    error_code = "NOT_FOUND"
    message = "Resource not found"


class UserNotFoundError(NotFoundError):
    error_code = "USER_NOT_FOUND"
    message = "User not found"


class OrganizationNotFoundError(NotFoundError):
    error_code = "ORGANIZATION_NOT_FOUND"
    message = "Organization not found"


class WorkspaceNotFoundError(NotFoundError):
    error_code = "WORKSPACE_NOT_FOUND"
    message = "Workspace not found"


class ProjectNotFoundError(NotFoundError):
    error_code = "PROJECT_NOT_FOUND"
    message = "Project not found"


class DocumentNotFoundError(NotFoundError):
    error_code = "DOCUMENT_NOT_FOUND"
    message = "Document not found"


class RequirementNotFoundError(NotFoundError):
    error_code = "REQUIREMENT_NOT_FOUND"
    message = "Requirement not found"


class StoryNotFoundError(NotFoundError):
    error_code = "STORY_NOT_FOUND"
    message = "User story not found"


class SprintNotFoundError(NotFoundError):
    error_code = "SPRINT_NOT_FOUND"
    message = "Sprint not found"


class TaskNotFoundError(NotFoundError):
    error_code = "TASK_NOT_FOUND"
    message = "Task not found"


# ── Conflict / Validation errors ──────────────────────────────────────────────

class ConflictError(SDDBaseException):
    status_code = 409
    error_code = "CONFLICT"
    message = "Resource already exists or conflict detected"


class EmailAlreadyExistsError(ConflictError):
    error_code = "EMAIL_ALREADY_EXISTS"
    message = "A user with this email address already exists"


class OrganizationSlugConflictError(ConflictError):
    error_code = "ORG_SLUG_CONFLICT"
    message = "An organization with this slug already exists"


class ValidationError(SDDBaseException):
    status_code = 422
    error_code = "VALIDATION_ERROR"
    message = "Validation failed"


class PasswordValidationError(ValidationError):
    error_code = "PASSWORD_VALIDATION_ERROR"
    message = "Password does not meet requirements"


class FileTooLargeError(ValidationError):
    error_code = "FILE_TOO_LARGE"
    message = "Uploaded file exceeds the maximum allowed size"


class InvalidFileTypeError(ValidationError):
    error_code = "INVALID_FILE_TYPE"
    message = "File type is not allowed"


# ── Business logic errors ─────────────────────────────────────────────────────

class WorkflowError(SDDBaseException):
    status_code = 400
    error_code = "WORKFLOW_ERROR"
    message = "Invalid workflow state transition"


class ApprovalError(SDDBaseException):
    status_code = 400
    error_code = "APPROVAL_ERROR"
    message = "Approval workflow error"


class AIGenerationError(SDDBaseException):
    status_code = 500
    error_code = "AI_GENERATION_ERROR"
    message = "AI generation failed"


class AIRateLimitError(SDDBaseException):
    status_code = 429
    error_code = "AI_RATE_LIMIT"
    message = "AI generation rate limit exceeded"


class SprintCapacityError(SDDBaseException):
    status_code = 400
    error_code = "SPRINT_CAPACITY_EXCEEDED"
    message = "Sprint capacity exceeded"


class RateLimitExceededError(SDDBaseException):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"
    message = "Rate limit exceeded. Please slow down your requests"


# ── Tenant / Multi-tenancy errors ─────────────────────────────────────────────

class TenantError(SDDBaseException):
    status_code = 403
    error_code = "TENANT_ERROR"
    message = "Tenant isolation violation"


class CrossTenantAccessError(TenantError):
    error_code = "CROSS_TENANT_ACCESS"
    message = "Access to resources from a different organization is not allowed"


# ── Infrastructure errors ─────────────────────────────────────────────────────

class DatabaseError(SDDBaseException):
    status_code = 500
    error_code = "DATABASE_ERROR"
    message = "A database error occurred"


class CacheError(SDDBaseException):
    status_code = 500
    error_code = "CACHE_ERROR"
    message = "A cache error occurred"


class StorageError(SDDBaseException):
    status_code = 500
    error_code = "STORAGE_ERROR"
    message = "A file storage error occurred"


class ExternalServiceError(SDDBaseException):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"
    message = "An external service returned an error"
