"""credit_note_apply

Revision ID: d2e3f4g5h6i7
Revises: c1d2e3f4g5h6
Create Date: 2026-03-17 15:00:00.000000

Add application tracking fields to credit_note table:
status, applied_to_ar_id, applied_amount, applied_at, applied_by.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd2e3f4g5h6i7'
down_revision = 'c1d2e3f4g5h6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('credit_note', sa.Column('status', sa.String(20), nullable=False, server_default='unapplied'))
    op.add_column('credit_note', sa.Column('applied_to_ar_id', sa.Integer(),
                                           sa.ForeignKey('account_receivable.id', ondelete='SET NULL'),
                                           nullable=True))
    op.add_column('credit_note', sa.Column('applied_amount', sa.Numeric(10, 2), nullable=True))
    op.add_column('credit_note', sa.Column('applied_at', sa.DateTime(), nullable=True))
    op.add_column('credit_note', sa.Column('applied_by', sa.Integer(),
                                           sa.ForeignKey('user.id', ondelete='SET NULL'),
                                           nullable=True))


def downgrade():
    op.drop_column('credit_note', 'applied_by')
    op.drop_column('credit_note', 'applied_at')
    op.drop_column('credit_note', 'applied_amount')
    op.drop_column('credit_note', 'applied_to_ar_id')
    op.drop_column('credit_note', 'status')
