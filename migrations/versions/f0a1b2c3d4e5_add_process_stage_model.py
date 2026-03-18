"""add process_stage model

Revision ID: f0a1b2c3d4e5
Revises: d5e6f7g8h9i0
Create Date: 2026-03-10 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f0a1b2c3d4e5'
down_revision = 'd5e6f7g8h9i0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'process_stage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('order', sa.Integer(), nullable=True),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('sla_hours', sa.Integer(), nullable=True),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_process_stage_tenant', 'process_stage', ['tenant_id'])


def downgrade():
    op.drop_index('ix_process_stage_tenant', table_name='process_stage')
    op.drop_table('process_stage')
