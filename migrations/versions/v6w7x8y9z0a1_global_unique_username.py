"""Enforce globally unique usernames (drop per-tenant constraint, add global unique)

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'v6w7x8y9z0a1'
down_revision = 'u5v6w7x8y9z0'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the old per-tenant composite unique constraint
    op.drop_constraint('uq_username_per_tenant', 'user', type_='unique')
    # Add a globally unique constraint on username alone
    op.create_unique_constraint('uq_username_global', 'user', ['username'])


def downgrade():
    op.drop_constraint('uq_username_global', 'user', type_='unique')
    op.create_unique_constraint('uq_username_per_tenant', 'user', ['username', 'tenant_id'])
