"""add time tracking columns

Revision ID: g1h2i3j4k5l6
Revises: f0a1b2c3d4e5
Create Date: 2026-03-10 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'g1h2i3j4k5l6'
down_revision = 'f0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product_instance',
        sa.Column('entered_stage_at', sa.DateTime(), nullable=True))
    op.add_column('product_process_log',
        sa.Column('duration_minutes', sa.Integer(), nullable=True))
    op.alter_column('product_process_log', 'action',
        existing_type=sa.String(20), type_=sa.String(50))


def downgrade():
    op.drop_column('product_instance', 'entered_stage_at')
    op.drop_column('product_process_log', 'duration_minutes')
    op.alter_column('product_process_log', 'action',
        existing_type=sa.String(50), type_=sa.String(20))
