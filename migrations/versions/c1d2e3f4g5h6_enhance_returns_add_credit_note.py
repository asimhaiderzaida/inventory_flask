"""enhance_returns_add_credit_note

Revision ID: c1d2e3f4g5h6
Revises: b3c4d5e6f7a8
Create Date: 2026-03-17 14:00:00.000000

Enhance the returns table with unit/part type support, refund tracking,
credit note fields, and add the credit_note table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d2e3f4g5h6'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    # ── Enhance returns table ──────────────────────────────────────────────

    # Make instance_id nullable (was NOT NULL) so part returns have no instance
    op.alter_column('returns', 'instance_id',
                    existing_type=sa.Integer(),
                    nullable=True)

    # Change CASCADE on instance_id FK to SET NULL
    op.drop_constraint('returns_instance_id_fkey', 'returns', type_='foreignkey')
    op.create_foreign_key(
        'returns_instance_id_fkey', 'returns',
        'product_instance', ['instance_id'], ['id'],
        ondelete='SET NULL'
    )

    # New columns
    op.add_column('returns', sa.Column('return_type', sa.String(10), nullable=False, server_default='unit'))
    op.add_column('returns', sa.Column('invoice_id', sa.Integer(), sa.ForeignKey('invoice.id', ondelete='SET NULL'), nullable=True))
    op.add_column('returns', sa.Column('order_id', sa.Integer(), sa.ForeignKey('customer_order_tracking.id', ondelete='SET NULL'), nullable=True))
    op.add_column('returns', sa.Column('part_id', sa.Integer(), sa.ForeignKey('part.id', ondelete='SET NULL'), nullable=True))
    op.add_column('returns', sa.Column('part_quantity', sa.Integer(), nullable=True))
    op.add_column('returns', sa.Column('part_sale_id', sa.Integer(), sa.ForeignKey('part_sale_transaction.id', ondelete='SET NULL'), nullable=True))
    op.add_column('returns', sa.Column('action_taken', sa.String(255), nullable=True))
    op.add_column('returns', sa.Column('refund_amount', sa.Numeric(10, 2), nullable=True))
    op.add_column('returns', sa.Column('refund_method', sa.String(32), nullable=True))
    op.add_column('returns', sa.Column('refund_status', sa.String(16), nullable=False, server_default='pending'))
    op.add_column('returns', sa.Column('credit_note_number', sa.String(32), nullable=True))
    op.add_column('returns', sa.Column('credit_note_issued_at', sa.DateTime(), nullable=True))

    # Index on tenant_id
    op.create_index('ix_returns_tenant_id', 'returns', ['tenant_id'])

    # ── Create credit_note table ───────────────────────────────────────────
    op.create_table(
        'credit_note',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenant.id', ondelete='CASCADE'), nullable=False),
        sa.Column('return_id', sa.Integer(), sa.ForeignKey('returns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('credit_note_number', sa.String(32), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='USD'),
        sa.Column('issued_at', sa.DateTime(), nullable=True),
        sa.Column('issued_by', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.UniqueConstraint('credit_note_number', 'tenant_id', name='uix_credit_note_tenant'),
        sa.Index('ix_credit_note_tenant', 'tenant_id'),
    )


def downgrade():
    op.drop_table('credit_note')

    op.drop_index('ix_returns_tenant_id', table_name='returns')
    op.drop_column('returns', 'credit_note_issued_at')
    op.drop_column('returns', 'credit_note_number')
    op.drop_column('returns', 'refund_status')
    op.drop_column('returns', 'refund_method')
    op.drop_column('returns', 'refund_amount')
    op.drop_column('returns', 'action_taken')
    op.drop_column('returns', 'part_sale_id')
    op.drop_column('returns', 'part_quantity')
    op.drop_column('returns', 'part_id')
    op.drop_column('returns', 'order_id')
    op.drop_column('returns', 'invoice_id')
    op.drop_column('returns', 'return_type')

    op.drop_constraint('returns_instance_id_fkey', 'returns', type_='foreignkey')
    op.create_foreign_key(
        'returns_instance_id_fkey', 'returns',
        'product_instance', ['instance_id'], ['id'],
        ondelete='CASCADE'
    )
    op.alter_column('returns', 'instance_id',
                    existing_type=sa.Integer(),
                    nullable=False)
