"""Add delivered_by_user_id to customer_order_tracking

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'u5v6w7x8y9z0'
down_revision = 't4u5v6w7x8y9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('customer_order_tracking',
        sa.Column('delivered_by_user_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))


def downgrade():
    op.drop_column('customer_order_tracking', 'delivered_by_user_id')
