"""Fix users table to match current model.

Revision ID: 002
Revises: 001
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Add missing columns (skip if already exists)
    existing = {row[0] for row in conn.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name='users'")
    )}

    if 'role' not in existing:
        op.add_column('users', sa.Column('role', sa.String(50), nullable=False, server_default='developer'))

    if 'is_active' not in existing:
        op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))

    if 'is_verified' not in existing:
        op.add_column('users', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'))

    if 'phone' not in existing:
        op.add_column('users', sa.Column('phone', sa.String(30), nullable=True))

    if 'last_login_ip' not in existing:
        op.add_column('users', sa.Column('last_login_ip', sa.String(45), nullable=True))

    if 'password_changed_at' not in existing:
        op.add_column('users', sa.Column('password_changed_at', sa.TIMESTAMP(timezone=True), nullable=True))

    if 'organization_id' not in existing:
        op.add_column('users', sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key('fk_users_organization', 'users', 'organizations', ['organization_id'], ['id'], ondelete='SET NULL')

    # Add missing indexes
    existing_indexes = {row[0] for row in conn.execute(
        sa.text("SELECT indexname FROM pg_indexes WHERE tablename='users'")
    )}
    if 'ix_users_is_active' not in existing_indexes:
        op.create_index('ix_users_is_active', 'users', ['is_active'])
    if 'ix_users_role' not in existing_indexes:
        op.create_index('ix_users_role', 'users', ['role'])
    if 'ix_users_organization_id' not in existing_indexes and 'organization_id' in existing or 'organization_id' not in existing:
        try:
            op.create_index('ix_users_organization_id', 'users', ['organization_id'])
        except Exception:
            pass

    # Fix locale column length (model uses String(10), migration used String(20))
    # Also ensure workspace and project member tables exist with correct columns
    # Add missing workspace_members table columns
    existing_tables = {row[0] for row in conn.execute(
        sa.text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    )}

    if 'workspace_members' not in existing_tables:
        op.create_table(
            'workspace_members',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('role', sa.String(50), nullable=False, server_default='member'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()'), nullable=False),
            sa.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_member'),
        )
        op.create_index('ix_workspace_member_user', 'workspace_members', ['user_id'])
        op.create_index('ix_workspace_members_created_at', 'workspace_members', ['created_at'])


def downgrade() -> None:
    pass
