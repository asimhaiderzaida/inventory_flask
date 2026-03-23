"""Add stage tracking fields to CustomerOrderTracking.

Revision ID: t1r2a3c4k5s6
Revises: c1u2s3t4o5r6
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = 't1r2a3c4k5s6'
down_revision = 'c1u2s3t4o5r6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('customer_order_tracking',
        sa.Column('current_stage', sa.String(100), nullable=True))
    op.add_column('customer_order_tracking',
        sa.Column('stage_updated_at', sa.DateTime(), nullable=True))
    op.add_column('customer_order_tracking',
        sa.Column('stage_history', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('customer_order_tracking', 'stage_history')
    op.drop_column('customer_order_tracking', 'stage_updated_at')
    op.drop_column('customer_order_tracking', 'current_stage')
