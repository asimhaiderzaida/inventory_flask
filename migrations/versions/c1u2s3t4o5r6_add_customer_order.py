"""Add CustomerOrder model for purchase order tracking.

Revision ID: c1u2s3t4o5r6
Revises: r1e2s3e4r5v6
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1u2s3t4o5r6'
down_revision = 'r1e2s3e4r5v6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'customer_order',
        sa.Column('id',                sa.Integer(),      nullable=False),
        sa.Column('tenant_id',         sa.Integer(),      nullable=False),
        sa.Column('customer_id',       sa.Integer(),      nullable=True),
        sa.Column('customer_name',     sa.String(120),    nullable=False),
        sa.Column('model_description', sa.String(255),    nullable=False),
        sa.Column('quantity',          sa.Integer(),      nullable=False, server_default='1'),
        sa.Column('expected_price',    sa.Numeric(10, 2), nullable=True),
        sa.Column('total_budget',      sa.Numeric(10, 2), nullable=True),
        sa.Column('delivery_date',     sa.Date(),         nullable=True),
        sa.Column('deposit_amount',    sa.Numeric(10, 2), nullable=True),
        sa.Column('deposit_paid',      sa.Boolean(),      nullable=False, server_default='false'),
        sa.Column('payment_status',    sa.String(20),     nullable=False, server_default='none'),
        sa.Column('status',            sa.String(20),     nullable=False, server_default='open'),
        sa.Column('notes',             sa.Text(),         nullable=True),
        sa.Column('created_by',        sa.Integer(),      nullable=True),
        sa.Column('created_at',        sa.DateTime(),     nullable=False,
                  server_default=sa.func.now()),
        sa.Column('closed_at',         sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],   ['tenant.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'],  ['user.id'],     ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_customer_order_tenant_status', 'customer_order',
                    ['tenant_id', 'status'])
    op.create_index('ix_customer_order_tenant_id',     'customer_order', ['tenant_id'])


def downgrade():
    op.drop_index('ix_customer_order_tenant_status', table_name='customer_order')
    op.drop_index('ix_customer_order_tenant_id',     table_name='customer_order')
    op.drop_table('customer_order')
