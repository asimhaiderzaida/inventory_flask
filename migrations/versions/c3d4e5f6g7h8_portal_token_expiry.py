"""portal_token_expiry_and_partsale_cleanup

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-03-25 12:00:00.000000

Add portal_token_expires_at to customer (L9: 30-day token TTL).
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6g7h8'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('portal_token_expires_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.drop_column('portal_token_expires_at')
