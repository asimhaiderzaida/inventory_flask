"""Add Shopify integration models and shopify_listed column

Revision ID: s1h2o3p4i5f6
Revises: z2a3b4c5d6e7
Create Date: 2026-03-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 's1h2o3p4i5f6'
down_revision = '7217c0936f8e'
branch_labels = None
depends_on = None


def upgrade():
    # shopify_listed on product_instance
    op.add_column('product_instance',
        sa.Column('shopify_listed', sa.Boolean(), nullable=False, server_default='false')
    )

    # shopify_product table
    op.create_table('shopify_product',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_key', sa.String(200)),
        sa.Column('shopify_product_id', sa.String(50)),
        sa.Column('shopify_variant_id', sa.String(50)),
        sa.Column('shopify_inventory_item_id', sa.String(50)),
        sa.Column('shopify_location_id', sa.String(50)),
        sa.Column('sync_status', sa.String(20), server_default='synced'),
        sa.Column('sync_error', sa.Text()),
        sa.Column('last_synced_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index('ix_shopify_product_tenant_key', 'shopify_product', ['tenant_id', 'product_key'])

    # shopify_sync_log table
    op.create_table('shopify_sync_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(50)),
        sa.Column('direction', sa.String(10)),
        sa.Column('status', sa.String(20)),
        sa.Column('details', sa.Text()),
        sa.Column('shopify_id', sa.String(50)),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index('ix_shopify_sync_log_tenant', 'shopify_sync_log', ['tenant_id', 'created_at'])

    # shopify_order table
    op.create_table('shopify_order',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('shopify_order_id', sa.String(50), unique=True, nullable=False),
        sa.Column('shopify_order_number', sa.String(50)),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id', ondelete='SET NULL')),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('total_price', sa.Numeric(10, 2)),
        sa.Column('currency', sa.String(10)),
        sa.Column('payment_method', sa.String(50)),
        sa.Column('shopify_data', sa.Text()),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('processed_at', sa.DateTime()),
        sa.Column('processed_by', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL')),
    )
    op.create_index('ix_shopify_order_tenant_status', 'shopify_order', ['tenant_id', 'status'])


def downgrade():
    op.drop_index('ix_shopify_order_tenant_status', table_name='shopify_order')
    op.drop_table('shopify_order')
    op.drop_index('ix_shopify_sync_log_tenant', table_name='shopify_sync_log')
    op.drop_table('shopify_sync_log')
    op.drop_index('ix_shopify_product_tenant_key', table_name='shopify_product')
    op.drop_table('shopify_product')
    op.drop_column('product_instance', 'shopify_listed')
