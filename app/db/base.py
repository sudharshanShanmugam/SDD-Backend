"""Import all models here so Alembic can detect them via autogenerate."""
from app.models.base import Base  # noqa: F401

# Import every model so SQLAlchemy's metadata is populated
from app.models.user import User  # noqa: F401
from app.models.organization import Organization, OrganizationMember  # noqa: F401
from app.models.workspace import Workspace, WorkspaceMember  # noqa: F401
from app.models.project import Project, ProjectMember  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401
from app.models.user_story import UserStory  # noqa: F401
from app.models.sprint import Sprint, SprintUserStory  # noqa: F401
from app.models.task import Task  # noqa: F401
from app.models.approval import Approval, ApprovalComment  # noqa: F401
from app.models.ai_generation import AIGeneration  # noqa: F401
from app.models.workflow import WorkflowState  # noqa: F401
from app.models.workflow_run import WorkflowRun  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.release import Release, ReleaseItem  # noqa: F401
from app.models.qa_test_case import QATestCase, QATestStep  # noqa: F401
