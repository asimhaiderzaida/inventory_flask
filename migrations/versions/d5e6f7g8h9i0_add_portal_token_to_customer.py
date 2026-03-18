"""add portal_token to customer

Revision ID: d5e6f7g8h9i0
Revises: c9d8e7f6a5b4
Create Date: 2026-03-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7g8h9i0'
down_revision = 'c9d8e7f6a5b4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('customer', sa.Column('portal_token', sa.String(48), nullable=True))
    op.create_index('ix_customer_portal_token', 'customer', ['portal_token'], unique=True)


def downgrade():
    op.drop_index('ix_customer_portal_token', table_name='customer')
    op.drop_column('customer', 'portal_token')
