"""Add payment_method and payment_status to SaleTransaction and Invoice

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa

revision = 's3t4u5v6w7x8'
down_revision = 'r2s3t4u5v6w7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sale_transaction',
        sa.Column('payment_method', sa.String(16), nullable=True))
    op.add_column('sale_transaction',
        sa.Column('payment_status', sa.String(16), nullable=True, server_default='paid'))

    op.add_column('invoice',
        sa.Column('payment_method', sa.String(16), nullable=True))
    op.add_column('invoice',
        sa.Column('payment_status', sa.String(16), nullable=True, server_default='paid'))


def downgrade():
    op.drop_column('invoice', 'payment_status')
    op.drop_column('invoice', 'payment_method')
    op.drop_column('sale_transaction', 'payment_status')
    op.drop_column('sale_transaction', 'payment_method')
