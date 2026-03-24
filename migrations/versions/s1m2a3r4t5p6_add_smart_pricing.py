"""add_smart_pricing

Revision ID: s1m2a3r4t5p6
Revises: p1e2r3m4i5s6
Create Date: 2026-03-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 's1m2a3r4t5p6'
down_revision = 'p1e2r3m4i5s6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'unit_cost',
        sa.Column('id',               sa.Integer(),     primary_key=True),
        sa.Column('instance_id',      sa.Integer(),     sa.ForeignKey('product_instance.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('tenant_id',        sa.Integer(),     sa.ForeignKey('tenant.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('purchase_cost',    sa.Numeric(10,2), server_default='0'),
        sa.Column('shipping_cost',    sa.Numeric(10,2), server_default='0'),
        sa.Column('duty_amount',      sa.Numeric(10,2), server_default='0'),
        sa.Column('repair_cost',      sa.Numeric(10,2), server_default='0'),
        sa.Column('ram_upgrade_cost', sa.Numeric(10,2), server_default='0'),
        sa.Column('ssd_upgrade_cost', sa.Numeric(10,2), server_default='0'),
        sa.Column('other_cost',       sa.Numeric(10,2), server_default='0'),
        sa.Column('other_cost_note',  sa.String(200),   nullable=True),
        sa.Column('margin_percent',   sa.Numeric(5,2),  server_default='25'),
        sa.Column('total_cost',       sa.Numeric(10,2), server_default='0'),
        sa.Column('suggested_price',  sa.Numeric(10,2), server_default='0'),
        sa.Column('updated_at',       sa.DateTime(),    nullable=True),
    )
    op.create_index('ix_unit_cost_tenant_id', 'unit_cost', ['tenant_id'])

    op.create_table(
        'po_cost_settings',
        sa.Column('id',               sa.Integer(),     primary_key=True),
        sa.Column('po_id',            sa.Integer(),     sa.ForeignKey('purchase_order.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('tenant_id',        sa.Integer(),     sa.ForeignKey('tenant.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('total_shipping',   sa.Numeric(10,2), server_default='0'),
        sa.Column('shipping_per_unit',sa.Numeric(10,2), server_default='0'),
        sa.Column('shipping_mode',    sa.String(10),    server_default='shared'),
        sa.Column('duty_type',        sa.String(10),    server_default='percent'),
        sa.Column('duty_value',       sa.Numeric(10,2), server_default='0'),
        sa.Column('default_margin',   sa.Numeric(5,2),  server_default='25'),
        sa.Column('updated_at',       sa.DateTime(),    nullable=True),
    )
    op.create_index('ix_po_cost_settings_tenant_id', 'po_cost_settings', ['tenant_id'])


def downgrade():
    op.drop_index('ix_po_cost_settings_tenant_id', table_name='po_cost_settings')
    op.drop_table('po_cost_settings')
    op.drop_index('ix_unit_cost_tenant_id', table_name='unit_cost')
    op.drop_table('unit_cost')
