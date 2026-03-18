"""add custom_field and custom_field_value tables

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-03-16

"""
from alembic import op
import sqlalchemy as sa

revision = 'z2a3b4c5d6e7'
down_revision = 'y1z2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'custom_field',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_key', sa.String(50), nullable=False),
        sa.Column('field_label', sa.String(100), nullable=False),
        sa.Column('field_type', sa.String(20), nullable=False, server_default='text'),
        sa.Column('field_options', sa.Text(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('show_in_list', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('show_in_invoice', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('tenant_id', 'field_key', name='uq_custom_field_tenant_key'),
    )
    op.create_index('ix_custom_field_tenant', 'custom_field', ['tenant_id'])

    op.create_table(
        'custom_field_value',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('instance_id', sa.Integer(), sa.ForeignKey('product_instance.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_id', sa.Integer(), sa.ForeignKey('custom_field.id', ondelete='CASCADE'), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.UniqueConstraint('instance_id', 'field_id', name='uq_cfv_instance_field'),
    )
    op.create_index('ix_cfv_instance', 'custom_field_value', ['instance_id'])


def downgrade():
    op.drop_index('ix_cfv_instance', table_name='custom_field_value')
    op.drop_table('custom_field_value')
    op.drop_index('ix_custom_field_tenant', table_name='custom_field')
    op.drop_table('custom_field')
