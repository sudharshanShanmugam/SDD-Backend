"""Initial schema - complete SDD platform database

Revision ID: 001_initial
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ─────────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "btree_gin"')

    # ── Enums ──────────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE user_status AS ENUM ('active', 'inactive', 'suspended', 'pending_verification')")
    op.execute("CREATE TYPE org_plan AS ENUM ('free', 'starter', 'professional', 'enterprise')")
    op.execute("CREATE TYPE project_role AS ENUM ('project_owner', 'business_analyst', 'product_owner', 'tech_lead', 'developer', 'qa_engineer', 'scrum_master', 'viewer')")
    op.execute("CREATE TYPE workflow_stage AS ENUM ('document_upload', 'requirement_extraction', 'requirement_review', 'epic_generation', 'epic_review', 'story_generation', 'story_review', 'sprint_planning', 'task_breakdown', 'spec_generation', 'qa_generation', 'development', 'testing', 'release', 'completed')")
    op.execute("CREATE TYPE document_status AS ENUM ('uploaded', 'queued', 'processing', 'processed', 'failed', 'archived')")
    op.execute("CREATE TYPE requirement_type AS ENUM ('functional', 'non_functional', 'business', 'technical', 'security', 'performance', 'compliance', 'constraint', 'assumption', 'dependency')")
    op.execute("CREATE TYPE priority_level AS ENUM ('critical', 'high', 'medium', 'low', 'backlog')")
    op.execute("CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'needs_revision', 'withdrawn')")
    op.execute("CREATE TYPE task_status AS ENUM ('backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled')")
    op.execute("CREATE TYPE sprint_status AS ENUM ('planning', 'active', 'review', 'retrospective', 'completed', 'cancelled')")
    op.execute("CREATE TYPE ai_generation_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled', 'awaiting_review', 'approved', 'rejected')")
    op.execute("CREATE TYPE ai_generation_type AS ENUM ('requirement_extraction', 'requirement_structuring', 'epic_generation', 'story_generation', 'sprint_planning', 'task_breakdown', 'ui_spec', 'api_spec', 'qa_generation', 'documentation', 'release_notes', 'risk_analysis', 'estimation', 'dependency_analysis', 'traceability')")
    op.execute("CREATE TYPE test_case_type AS ENUM ('functional', 'integration', 'e2e', 'performance', 'security', 'accessibility', 'regression', 'smoke', 'unit')")
    op.execute("CREATE TYPE notification_type AS ENUM ('approval_requested', 'approval_completed', 'ai_generation_complete', 'ai_generation_failed', 'document_processed', 'sprint_started', 'sprint_completed', 'task_assigned', 'task_status_changed', 'mention', 'comment', 'release_created', 'workflow_stage_changed', 'member_invited')")

    # ── Users ──────────────────────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('avatar_url', sa.String(500)),
        sa.Column('job_title', sa.String(255)),
        sa.Column('timezone', sa.String(100), server_default='UTC'),
        sa.Column('locale', sa.String(20), server_default='en-US'),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending_verification'),
        sa.Column('is_superuser', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('email_verified', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('email_verified_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('last_login_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('login_count', sa.Integer(), server_default='0'),
        sa.Column('failed_login_attempts', sa.Integer(), server_default='0'),
        sa.Column('locked_until', sa.TIMESTAMP(timezone=True)),
        sa.Column('preferences', postgresql.JSONB(), server_default='{}'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_status', 'users', ['status'])

    # ── Organizations ──────────────────────────────────────────────────────────
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.Text()),
        sa.Column('logo_url', sa.String(500)),
        sa.Column('website', sa.String(255)),
        sa.Column('plan', sa.String(50), nullable=False, server_default='free'),
        sa.Column('plan_expires_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('billing_email', sa.String(255)),
        sa.Column('settings', postgresql.JSONB(), server_default='{}'),
        sa.Column('feature_flags', postgresql.JSONB(), server_default='{}'),
        sa.Column('ai_tokens_used_month', sa.BigInteger(), server_default='0'),
        sa.Column('ai_tokens_reset_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('storage_used_bytes', sa.BigInteger(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_organizations_slug', 'organizations', ['slug'])
    op.create_index('ix_organizations_owner_id', 'organizations', ['owner_id'])

    # ── Organization Members ───────────────────────────────────────────────────
    op.create_table(
        'organization_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default='org_member'),
        sa.Column('joined_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_org_members'),
    )
    op.create_index('ix_org_members_org_id', 'organization_members', ['organization_id'])
    op.create_index('ix_org_members_user_id', 'organization_members', ['user_id'])

    # ── Workspaces ─────────────────────────────────────────────────────────────
    op.create_table(
        'workspaces',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('icon', sa.String(50)),
        sa.Column('color', sa.String(20)),
        sa.Column('settings', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='false'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
        sa.UniqueConstraint('organization_id', 'slug', name='uq_workspace_slug'),
    )
    op.create_index('ix_workspaces_org_id', 'workspaces', ['organization_id'])

    # ── Projects ───────────────────────────────────────────────────────────────
    op.create_table(
        'projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('key', sa.String(10), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('workflow_stage', sa.String(50), nullable=False, server_default='document_upload'),
        sa.Column('start_date', sa.Date()),
        sa.Column('target_date', sa.Date()),
        sa.Column('status', sa.String(50), server_default='active'),
        sa.Column('sprint_duration_weeks', sa.Integer(), server_default='2'),
        sa.Column('team_velocity', sa.Integer(), server_default='40'),
        sa.Column('settings', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
        sa.UniqueConstraint('workspace_id', 'key', name='uq_project_key'),
    )
    op.create_index('ix_projects_org_id', 'projects', ['organization_id'])
    op.create_index('ix_projects_workspace_id', 'projects', ['workspace_id'])
    op.create_index('ix_projects_stage', 'projects', ['workflow_stage'])

    # ── Project Members ────────────────────────────────────────────────────────
    op.create_table(
        'project_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('joined_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('added_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.UniqueConstraint('project_id', 'user_id', name='uq_project_members'),
    )
    op.create_index('ix_project_members_project_id', 'project_members', ['project_id'])
    op.create_index('ix_project_members_user_id', 'project_members', ['user_id'])

    # ── Documents ──────────────────────────────────────────────────────────────
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('file_type', sa.String(100), nullable=False),
        sa.Column('mime_type', sa.String(200)),
        sa.Column('file_size_bytes', sa.BigInteger()),
        sa.Column('storage_path', sa.String(1000), nullable=False),
        sa.Column('storage_backend', sa.String(50), server_default='local'),
        sa.Column('document_type', sa.String(50), server_default='other'),
        sa.Column('status', sa.String(50), nullable=False, server_default='uploaded'),
        sa.Column('page_count', sa.Integer()),
        sa.Column('word_count', sa.Integer()),
        sa.Column('chunk_count', sa.Integer(), server_default='0'),
        sa.Column('processing_started_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('processing_completed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('processing_error', sa.Text()),
        sa.Column('extracted_metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('ai_summary', sa.Text()),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('parent_document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id')),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_documents_org_id', 'documents', ['organization_id'])
    op.create_index('ix_documents_project_id', 'documents', ['project_id'])
    op.create_index('ix_documents_status', 'documents', ['status'])

    # ── Document Chunks ────────────────────────────────────────────────────────
    op.create_table(
        'document_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer()),
        sa.Column('section_title', sa.String(500)),
        sa.Column('page_number', sa.Integer()),
        sa.Column('chunk_metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('embedding_id', sa.String(255)),
        sa.Column('embedded_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_chunks_document_id', 'document_chunks', ['document_id'])
    op.create_index('ix_chunks_org_project', 'document_chunks', ['organization_id', 'project_id'])

    # ── Requirements ───────────────────────────────────────────────────────────
    op.create_table(
        'requirements',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id')),
        sa.Column('ai_generation_id', postgresql.UUID(as_uuid=True)),
        sa.Column('requirement_id', sa.String(50), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('type', sa.String(50), nullable=False, server_default='functional'),
        sa.Column('priority', sa.String(50), nullable=False, server_default='medium'),
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),
        sa.Column('acceptance_criteria', postgresql.JSONB(), server_default='[]'),
        sa.Column('dependencies', postgresql.JSONB(), server_default='[]'),
        sa.Column('assumptions', postgresql.JSONB(), server_default='[]'),
        sa.Column('source_reference', sa.String(500)),
        sa.Column('ai_confidence_score', sa.Float()),
        sa.Column('is_ambiguous', sa.Boolean(), server_default='false'),
        sa.Column('ambiguity_reason', sa.Text()),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('approved_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('labels', postgresql.JSONB(), server_default='[]'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
        sa.UniqueConstraint('project_id', 'requirement_id', name='uq_requirement_id'),
    )
    op.create_index('ix_requirements_project_id', 'requirements', ['project_id'])
    op.create_index('ix_requirements_type', 'requirements', ['type'])
    op.create_index('ix_requirements_priority', 'requirements', ['priority'])
    op.create_index('ix_requirements_status', 'requirements', ['status'])

    # ── Epics ──────────────────────────────────────────────────────────────────
    op.create_table(
        'epics',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ai_generation_id', postgresql.UUID(as_uuid=True)),
        sa.Column('epic_key', sa.String(50), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('business_value', sa.Text()),
        sa.Column('acceptance_criteria', postgresql.JSONB(), server_default='[]'),
        sa.Column('priority', sa.String(50), nullable=False, server_default='medium'),
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),
        sa.Column('estimated_effort', sa.String(20)),
        sa.Column('story_points_total', sa.Integer(), server_default='0'),
        sa.Column('linked_requirement_ids', postgresql.JSONB(), server_default='[]'),
        sa.Column('ai_confidence_score', sa.Float()),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('order_index', sa.Integer(), server_default='0'),
        sa.Column('color', sa.String(20)),
        sa.Column('labels', postgresql.JSONB(), server_default='[]'),
        sa.Column('target_date', sa.Date()),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('approved_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_epics_project_id', 'epics', ['project_id'])
    op.create_index('ix_epics_status', 'epics', ['status'])
    op.create_index('ix_epics_order', 'epics', ['project_id', 'order_index'])

    # ── User Stories ───────────────────────────────────────────────────────────
    op.create_table(
        'user_stories',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('epic_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('epics.id', ondelete='SET NULL')),
        sa.Column('sprint_id', postgresql.UUID(as_uuid=True)),
        sa.Column('ai_generation_id', postgresql.UUID(as_uuid=True)),
        sa.Column('story_key', sa.String(50), nullable=False),
        sa.Column('title', sa.String(1000), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('acceptance_criteria', postgresql.JSONB(), server_default='[]'),
        sa.Column('story_points', sa.Integer()),
        sa.Column('priority', sa.String(50), nullable=False, server_default='medium'),
        sa.Column('status', sa.String(50), nullable=False, server_default='backlog'),
        sa.Column('type', sa.String(50), server_default='feature'),
        sa.Column('dependencies', postgresql.JSONB(), server_default='[]'),
        sa.Column('labels', postgresql.JSONB(), server_default='[]'),
        sa.Column('invest_score', postgresql.JSONB(), server_default='{}'),
        sa.Column('ai_confidence_score', sa.Float()),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('order_index', sa.Integer(), server_default='0'),
        sa.Column('assignee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('approved_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_stories_project_id', 'user_stories', ['project_id'])
    op.create_index('ix_stories_epic_id', 'user_stories', ['epic_id'])
    op.create_index('ix_stories_sprint_id', 'user_stories', ['sprint_id'])
    op.create_index('ix_stories_status', 'user_stories', ['status'])

    # ── Sprints ────────────────────────────────────────────────────────────────
    op.create_table(
        'sprints',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ai_generation_id', postgresql.UUID(as_uuid=True)),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('goal', sa.Text()),
        sa.Column('sprint_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='planning'),
        sa.Column('start_date', sa.Date()),
        sa.Column('end_date', sa.Date()),
        sa.Column('capacity_points', sa.Integer()),
        sa.Column('committed_points', sa.Integer(), server_default='0'),
        sa.Column('completed_points', sa.Integer(), server_default='0'),
        sa.Column('velocity', sa.Integer()),
        sa.Column('retrospective_notes', sa.Text()),
        sa.Column('risks', postgresql.JSONB(), server_default='[]'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
        sa.UniqueConstraint('project_id', 'sprint_number', name='uq_sprint_number'),
    )
    op.create_index('ix_sprints_project_id', 'sprints', ['project_id'])
    op.create_index('ix_sprints_status', 'sprints', ['status'])

    op.create_foreign_key('fk_stories_sprint', 'user_stories', 'sprints', ['sprint_id'], ['id'], ondelete='SET NULL')

    # ── Tasks ──────────────────────────────────────────────────────────────────
    op.create_table(
        'tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sprint_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sprints.id', ondelete='SET NULL')),
        sa.Column('story_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('user_stories.id', ondelete='CASCADE')),
        sa.Column('parent_task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id')),
        sa.Column('ai_generation_id', postgresql.UUID(as_uuid=True)),
        sa.Column('task_key', sa.String(50), nullable=False),
        sa.Column('title', sa.String(1000), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('type', sa.String(50), server_default='feature'),
        sa.Column('status', sa.String(50), nullable=False, server_default='backlog'),
        sa.Column('priority', sa.String(50), server_default='medium'),
        sa.Column('story_points', sa.Integer()),
        sa.Column('estimated_hours', sa.Float()),
        sa.Column('actual_hours', sa.Float()),
        sa.Column('assignee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('reporter_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('labels', postgresql.JSONB(), server_default='[]'),
        sa.Column('dependencies', postgresql.JSONB(), server_default='[]'),
        sa.Column('technical_notes', sa.Text()),
        sa.Column('order_index', sa.Integer(), server_default='0'),
        sa.Column('blocked_reason', sa.Text()),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_tasks_project_id', 'tasks', ['project_id'])
    op.create_index('ix_tasks_sprint_id', 'tasks', ['sprint_id'])
    op.create_index('ix_tasks_story_id', 'tasks', ['story_id'])
    op.create_index('ix_tasks_assignee_id', 'tasks', ['assignee_id'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])

    # ── AI Generations ─────────────────────────────────────────────────────────
    op.create_table(
        'ai_generations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE')),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id')),
        sa.Column('workflow_run_id', postgresql.UUID(as_uuid=True)),
        sa.Column('generation_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('model_name', sa.String(100)),
        sa.Column('prompt_tokens', sa.Integer(), server_default='0'),
        sa.Column('completion_tokens', sa.Integer(), server_default='0'),
        sa.Column('total_tokens', sa.Integer(), server_default='0'),
        sa.Column('cost_usd', sa.Float(), server_default='0'),
        sa.Column('latency_ms', sa.Integer()),
        sa.Column('input_data', postgresql.JSONB()),
        sa.Column('output_data', postgresql.JSONB()),
        sa.Column('confidence_score', sa.Float()),
        sa.Column('confidence_breakdown', postgresql.JSONB()),
        sa.Column('error_message', sa.Text()),
        sa.Column('error_trace', sa.Text()),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('triggered_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_ai_gen_project_id', 'ai_generations', ['project_id'])
    op.create_index('ix_ai_gen_type', 'ai_generations', ['generation_type'])
    op.create_index('ix_ai_gen_status', 'ai_generations', ['status'])

    # ── Workflow Runs ──────────────────────────────────────────────────────────
    op.create_table(
        'workflow_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id')),
        sa.Column('workflow_type', sa.String(100), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='running'),
        sa.Column('current_stage', sa.String(100)),
        sa.Column('completed_stages', postgresql.JSONB(), server_default='[]'),
        sa.Column('state_data', postgresql.JSONB()),
        sa.Column('thread_id', sa.String(255)),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('error_message', sa.Text()),
        sa.Column('triggered_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('failed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_workflow_runs_project_id', 'workflow_runs', ['project_id'])
    op.create_index('ix_workflow_runs_status', 'workflow_runs', ['status'])
    op.create_index('ix_workflow_runs_thread_id', 'workflow_runs', ['thread_id'])

    # ── Approvals ──────────────────────────────────────────────────────────────
    op.create_table(
        'approvals',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workflow_runs.id')),
        sa.Column('ai_generation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ai_generations.id')),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('reviewer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('requester_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('comments', postgresql.JSONB(), server_default='[]'),
        sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('due_date', sa.TIMESTAMP(timezone=True)),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('original_data', postgresql.JSONB()),
        sa.Column('revised_data', postgresql.JSONB()),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_approvals_project_id', 'approvals', ['project_id'])
    op.create_index('ix_approvals_status', 'approvals', ['status'])
    op.create_index('ix_approvals_reviewer_id', 'approvals', ['reviewer_id'])
    op.create_index('ix_approvals_entity', 'approvals', ['entity_type', 'entity_id'])

    # ── QA Test Cases ──────────────────────────────────────────────────────────
    op.create_table(
        'qa_test_cases',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('story_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('user_stories.id', ondelete='CASCADE')),
        sa.Column('sprint_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sprints.id')),
        sa.Column('ai_generation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ai_generations.id')),
        sa.Column('test_key', sa.String(50), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('type', sa.String(50), nullable=False, server_default='functional'),
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),
        sa.Column('priority', sa.String(50), server_default='medium'),
        sa.Column('preconditions', sa.Text()),
        sa.Column('steps', postgresql.JSONB(), server_default='[]'),
        sa.Column('expected_result', sa.Text()),
        sa.Column('actual_result', sa.Text()),
        sa.Column('automation_code', sa.Text()),
        sa.Column('automation_framework', sa.String(50)),
        sa.Column('assignee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('executed_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('executed_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('ai_confidence_score', sa.Float()),
        sa.Column('labels', postgresql.JSONB(), server_default='[]'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_qa_project_id', 'qa_test_cases', ['project_id'])
    op.create_index('ix_qa_story_id', 'qa_test_cases', ['story_id'])
    op.create_index('ix_qa_status', 'qa_test_cases', ['status'])

    # ── Releases ───────────────────────────────────────────────────────────────
    op.create_table(
        'releases',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ai_generation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ai_generations.id')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('release_notes', sa.Text()),
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),
        sa.Column('release_date', sa.Date()),
        sa.Column('published_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('published_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('sprint_ids', postgresql.JSONB(), server_default='[]'),
        sa.Column('story_ids', postgresql.JSONB(), server_default='[]'),
        sa.Column('change_summary', postgresql.JSONB(), server_default='{}'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_releases_project_id', 'releases', ['project_id'])
    op.create_index('ix_releases_status', 'releases', ['status'])

    # ── Audit Logs ─────────────────────────────────────────────────────────────
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True)),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True)),
        sa.Column('entity_name', sa.String(500)),
        sa.Column('old_data', postgresql.JSONB()),
        sa.Column('new_data', postgresql.JSONB()),
        sa.Column('diff', postgresql.JSONB()),
        sa.Column('ip_address', sa.String(50)),
        sa.Column('user_agent', sa.Text()),
        sa.Column('request_id', sa.String(255)),
        sa.Column('session_id', sa.String(255)),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_audit_org_id', 'audit_logs', ['organization_id'])
    op.create_index('ix_audit_user_id', 'audit_logs', ['user_id'])
    op.create_index('ix_audit_entity', 'audit_logs', ['entity_type', 'entity_id'])
    op.create_index('ix_audit_created_at', 'audit_logs', ['created_at'])
    op.create_index('ix_audit_action', 'audit_logs', ['action'])

    # ── Notifications ──────────────────────────────────────────────────────────
    op.create_table(
        'notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(100), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text()),
        sa.Column('entity_type', sa.String(100)),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True)),
        sa.Column('entity_url', sa.String(500)),
        sa.Column('is_read', sa.Boolean(), server_default='false'),
        sa.Column('read_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('priority', sa.String(20), server_default='info'),
        sa.Column('data', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_is_read', 'notifications', ['user_id', 'is_read'])

    # ── AI Prompts ─────────────────────────────────────────────────────────────
    op.create_table(
        'ai_prompts',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('generation_type', sa.String(100), nullable=False),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('user_prompt_template', sa.Text()),
        sa.Column('variables', postgresql.JSONB(), server_default='[]'),
        sa.Column('model', sa.String(100), server_default='gpt-4o'),
        sa.Column('temperature', sa.Float(), server_default='0.1'),
        sa.Column('max_tokens', sa.Integer(), server_default='4096'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('is_default', sa.Boolean(), server_default='false'),
        sa.Column('version', sa.Integer(), server_default='1'),
        sa.Column('usage_count', sa.Integer(), server_default='0'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_ai_prompts_org_id', 'ai_prompts', ['organization_id'])
    op.create_index('ix_ai_prompts_type', 'ai_prompts', ['generation_type'])

    # ── Comments ───────────────────────────────────────────────────────────────
    op.create_table(
        'comments',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('comments.id')),
        sa.Column('mentions', postgresql.JSONB(), server_default='[]'),
        sa.Column('reactions', postgresql.JSONB(), server_default='{}'),
        sa.Column('is_edited', sa.Boolean(), server_default='false'),
        sa.Column('edited_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('ix_comments_entity', 'comments', ['entity_type', 'entity_id'])
    op.create_index('ix_comments_author', 'comments', ['author_id'])

    # ── Auto-update trigger ─────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    for table in ['users', 'organizations', 'workspaces', 'projects', 'documents',
                  'requirements', 'epics', 'user_stories', 'sprints', 'tasks',
                  'ai_generations', 'workflow_runs', 'approvals', 'qa_test_cases',
                  'releases', 'ai_prompts', 'comments']:
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    for table in ['comments', 'ai_prompts', 'notifications', 'audit_logs', 'releases',
                  'qa_test_cases', 'approvals', 'workflow_runs', 'ai_generations', 'tasks',
                  'sprints', 'user_stories', 'epics', 'requirements', 'document_chunks',
                  'documents', 'project_members', 'projects', 'workspaces',
                  'organization_members', 'organizations', 'users']:
        op.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
    for enum_name in ['user_status', 'org_plan', 'project_role', 'workflow_stage',
                      'document_status', 'requirement_type', 'priority_level',
                      'approval_status', 'task_status', 'sprint_status',
                      'ai_generation_status', 'ai_generation_type', 'test_case_type',
                      'notification_type']:
        op.execute(f'DROP TYPE IF EXISTS {enum_name}')
    op.execute('DROP FUNCTION IF EXISTS update_updated_at_column()')
