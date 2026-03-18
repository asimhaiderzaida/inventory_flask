"""vendor_enhancements

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-03-17 11:00:00.000000

Add website/city/country/payment_terms/notes/created_at to Vendor.
Add VendorNote table.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    # ── New columns on vendor ──────────────────────────────
    with op.batch_alter_table('vendor', schema=None) as batch_op:
        batch_op.add_column(sa.Column('website',       sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('city',          sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('country',       sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('payment_terms', sa.String(length=50),  nullable=True))
        batch_op.add_column(sa.Column('notes',         sa.Text(),             nullable=True))
        batch_op.add_column(sa.Column('created_at',    sa.DateTime(),         nullable=True))

    # ── VendorNote ────────────────────────────────────────
    op.create_table(
        'vendor_note',
        sa.Column('id',         sa.Integer(),  nullable=False),
        sa.Column('tenant_id',  sa.Integer(),  nullable=False),
        sa.Column('vendor_id',  sa.Integer(),  nullable=False),
        sa.Column('note',       sa.Text(),     nullable=False),
        sa.Column('created_by', sa.Integer(),  nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],  ['tenant.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vendor_id'],  ['vendor.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'],   ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('vendor_note', schema=None) as batch_op:
        batch_op.create_index('ix_vendor_note_vendor', ['vendor_id'], unique=False)


def downgrade():
    with op.batch_alter_table('vendor_note', schema=None) as batch_op:
        batch_op.drop_index('ix_vendor_note_vendor')
    op.drop_table('vendor_note')

    with op.batch_alter_table('vendor', schema=None) as batch_op:
        batch_op.drop_column('created_at')
        batch_op.drop_column('notes')
        batch_op.drop_column('payment_terms')
        batch_op.drop_column('country')
        batch_op.drop_column('city')
        batch_op.drop_column('website')
