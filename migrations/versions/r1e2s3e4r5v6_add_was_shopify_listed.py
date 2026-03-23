"""Add was_shopify_listed to customer_order_tracking

Revision ID: r1e2s3e4r5v6
Revises: s1h2o3p4i5f6
Create Date: 2026-03-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'r1e2s3e4r5v6'
down_revision = 's1h2o3p4i5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'customer_order_tracking',
        sa.Column('was_shopify_listed', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade():
    op.drop_column('customer_order_tracking', 'was_shopify_listed')
