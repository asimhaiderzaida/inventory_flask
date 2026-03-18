"""add asking_price to product_instance

Revision ID: c9d8e7f6a5b4
Revises: a1b2c3d4e5f6
Create Date: 2026-03-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d8e7f6a5b4'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product_instance', sa.Column('asking_price', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('product_instance', 'asking_price')
