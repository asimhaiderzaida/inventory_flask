"""add_user_permission table

Revision ID: p1e2r3m4i5s6
Revises: 031055a347d6
Create Date: 2026-03-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'p1e2r3m4i5s6'
down_revision = '031055a347d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_permission',
        sa.Column('id',           sa.Integer(),     primary_key=True),
        sa.Column('user_id',      sa.Integer(),     sa.ForeignKey('user.id',   ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id',    sa.Integer(),     sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('module',       sa.String(50),    nullable=False),
        sa.Column('access_level', sa.String(20),    server_default='none', nullable=False),
        sa.UniqueConstraint('user_id', 'module', name='uq_user_permission'),
    )
    op.create_index('ix_user_permission_user_id',   'user_permission', ['user_id'])
    op.create_index('ix_user_permission_tenant_id', 'user_permission', ['tenant_id'])


def downgrade():
    op.drop_index('ix_user_permission_tenant_id', table_name='user_permission')
    op.drop_index('ix_user_permission_user_id',   table_name='user_permission')
    op.drop_table('user_permission')
