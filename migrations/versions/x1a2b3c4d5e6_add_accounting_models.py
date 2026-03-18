"""Add accounting models: ExpenseCategory, Expense, AccountReceivable, ARPayment, OtherIncome

Revision ID: x1a2b3c4d5e6
Revises: w7x8y9z0a1b2
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'x1a2b3c4d5e6'
down_revision = 'w7x8y9z0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    # ── expense_category ──────────────────────────────────────
    op.create_table(
        'expense_category',
        sa.Column('id',        sa.Integer(),     nullable=False),
        sa.Column('name',      sa.String(80),    nullable=False),
        sa.Column('slug',      sa.String(80),    nullable=False),
        sa.Column('icon',      sa.String(50),    nullable=True,  server_default='bi-receipt'),
        sa.Column('tenant_id', sa.Integer(),     nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', 'tenant_id', name='uq_expense_category_slug_tenant'),
    )
    op.create_index('ix_expense_category_tenant', 'expense_category', ['tenant_id'])

    # ── expense ───────────────────────────────────────────────
    op.create_table(
        'expense',
        sa.Column('id',             sa.Integer(),      nullable=False),
        sa.Column('tenant_id',      sa.Integer(),      nullable=False),
        sa.Column('category_id',    sa.Integer(),      nullable=True),
        sa.Column('amount',         sa.Numeric(10, 2), nullable=False),
        sa.Column('currency',       sa.String(10),     nullable=True,  server_default='AED'),
        sa.Column('description',    sa.String(255),    nullable=False),
        sa.Column('reference',      sa.String(100),    nullable=True),
        sa.Column('expense_date',   sa.Date(),         nullable=False),
        sa.Column('payment_method', sa.String(20),     nullable=True,  server_default='cash'),
        sa.Column('paid_by',        sa.Integer(),      nullable=True),
        sa.Column('vendor_id',      sa.Integer(),      nullable=True),
        sa.Column('po_id',          sa.Integer(),      nullable=True),
        sa.Column('receipt_url',    sa.String(255),    nullable=True),
        sa.Column('notes',          sa.Text(),         nullable=True),
        sa.Column('created_at',     sa.DateTime(),     nullable=True),
        sa.Column('created_by',     sa.Integer(),      nullable=True),
        sa.Column('deleted_at',     sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],   ['tenant.id'],           ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['expense_category.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['paid_by'],     ['user.id'],             ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['vendor_id'],   ['vendor.id'],           ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['po_id'],       ['purchase_order.id'],   ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'],  ['user.id'],             ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_expense_tenant_date', 'expense', ['tenant_id', 'expense_date'])

    # ── account_receivable ────────────────────────────────────
    op.create_table(
        'account_receivable',
        sa.Column('id',          sa.Integer(),      nullable=False),
        sa.Column('tenant_id',   sa.Integer(),      nullable=False),
        sa.Column('customer_id', sa.Integer(),      nullable=False),
        sa.Column('invoice_id',  sa.Integer(),      nullable=True),
        sa.Column('sale_id',     sa.Integer(),      nullable=True),
        sa.Column('amount_due',  sa.Numeric(10, 2), nullable=False),
        sa.Column('amount_paid', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('currency',    sa.String(10),     nullable=True, server_default='AED'),
        sa.Column('due_date',    sa.Date(),         nullable=True),
        sa.Column('status',      sa.String(20),     nullable=False, server_default='open'),
        sa.Column('notes',       sa.Text(),         nullable=True),
        sa.Column('created_at',  sa.DateTime(),     nullable=True),
        sa.Column('updated_at',  sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],   ['tenant.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invoice_id'],  ['invoice.id'],  ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['sale_id'],     ['order.id'],    ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ar_tenant_status', 'account_receivable', ['tenant_id', 'status'])
    op.create_index('ix_ar_customer',      'account_receivable', ['customer_id'])

    # ── ar_payment ────────────────────────────────────────────
    op.create_table(
        'ar_payment',
        sa.Column('id',             sa.Integer(),      nullable=False),
        sa.Column('tenant_id',      sa.Integer(),      nullable=False),
        sa.Column('ar_id',          sa.Integer(),      nullable=False),
        sa.Column('amount',         sa.Numeric(10, 2), nullable=False),
        sa.Column('payment_method', sa.String(20),     nullable=True, server_default='cash'),
        sa.Column('payment_date',   sa.Date(),         nullable=False),
        sa.Column('reference',      sa.String(100),    nullable=True),
        sa.Column('recorded_by',    sa.Integer(),      nullable=True),
        sa.Column('notes',          sa.Text(),         nullable=True),
        sa.Column('created_at',     sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],   ['tenant.id'],          ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ar_id'],       ['account_receivable.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recorded_by'], ['user.id'],            ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ar_payment_ar', 'ar_payment', ['ar_id'])

    # ── other_income ──────────────────────────────────────────
    op.create_table(
        'other_income',
        sa.Column('id',          sa.Integer(),      nullable=False),
        sa.Column('tenant_id',   sa.Integer(),      nullable=False),
        sa.Column('amount',      sa.Numeric(10, 2), nullable=False),
        sa.Column('currency',    sa.String(10),     nullable=True, server_default='AED'),
        sa.Column('description', sa.String(255),    nullable=False),
        sa.Column('income_date', sa.Date(),         nullable=False),
        sa.Column('reference',   sa.String(100),    nullable=True),
        sa.Column('notes',       sa.Text(),         nullable=True),
        sa.Column('created_at',  sa.DateTime(),     nullable=True),
        sa.Column('created_by',  sa.Integer(),      nullable=True),
        sa.Column('deleted_at',  sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],  ['tenant.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'],   ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_other_income_tenant_date', 'other_income', ['tenant_id', 'income_date'])


def downgrade():
    op.drop_table('other_income')
    op.drop_table('ar_payment')
    op.drop_table('account_receivable')
    op.drop_table('expense')
    op.drop_table('expense_category')
