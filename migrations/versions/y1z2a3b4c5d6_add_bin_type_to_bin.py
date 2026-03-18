"""add bin_type to bin

Revision ID: y1z2a3b4c5d6
Revises: x1a2b3c4d5e6
Create Date: 2026-03-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'y1z2a3b4c5d6'
down_revision = 'x1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bin', sa.Column(
        'bin_type', sa.String(10), nullable=False, server_default='units'
    ))


def downgrade():
    op.drop_column('bin', 'bin_type')
