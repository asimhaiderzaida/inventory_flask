"""Add full_name column to user table

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'w7x8y9z0a1b2'
down_revision = 'v6w7x8y9z0a1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('full_name', sa.String(120), nullable=True))


def downgrade():
    op.drop_column('user', 'full_name')
