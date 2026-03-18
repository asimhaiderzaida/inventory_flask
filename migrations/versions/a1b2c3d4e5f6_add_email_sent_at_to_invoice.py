"""add email_sent_at to invoice

Revision ID: a1b2c3d4e5f6
Revises: 7c1ceb739b80
Create Date: 2026-03-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '7c1ceb739b80'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('invoice', sa.Column('email_sent_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('invoice', 'email_sent_at')
