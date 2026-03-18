"""Add soft-delete fields to customer_order_tracking

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 't4u5v6w7x8y9'
down_revision = 's3t4u5v6w7x8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('customer_order_tracking',
        sa.Column('cancelled_at', sa.DateTime(), nullable=True))
    op.add_column('customer_order_tracking',
        sa.Column('cancelled_by_user_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))
    op.add_column('customer_order_tracking',
        sa.Column('reserved_by_user_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))


def downgrade():
    op.drop_column('customer_order_tracking', 'reserved_by_user_id')
    op.drop_column('customer_order_tracking', 'cancelled_by_user_id')
    op.drop_column('customer_order_tracking', 'cancelled_at')
