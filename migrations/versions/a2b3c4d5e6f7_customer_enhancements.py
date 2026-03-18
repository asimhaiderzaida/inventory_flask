"""customer_enhancements

Revision ID: a2b3c4d5e6f7
Revises: 31ce5b60df76
Create Date: 2026-03-17 10:00:00.000000

Add company/address/city/country/notes/created_at to Customer.
Add CustomerNote and CustomerCommunication tables.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a2b3c4d5e6f7'
down_revision = '31ce5b60df76'
branch_labels = None
depends_on = None


def upgrade():
    # ── New columns on customer ──────────────────────────────
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company',    sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('address',    sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('city',       sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('country',    sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('notes',      sa.Text(),             nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(),         nullable=True))

    # ── CustomerNote ─────────────────────────────────────────
    op.create_table(
        'customer_note',
        sa.Column('id',          sa.Integer(),     nullable=False),
        sa.Column('tenant_id',   sa.Integer(),     nullable=False),
        sa.Column('customer_id', sa.Integer(),     nullable=False),
        sa.Column('note',        sa.Text(),        nullable=False),
        sa.Column('created_by',  sa.Integer(),     nullable=True),
        sa.Column('created_at',  sa.DateTime(),    nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],   ['tenant.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'],  ['user.id'],     ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('customer_note', schema=None) as batch_op:
        batch_op.create_index('ix_customer_note_customer', ['customer_id'], unique=False)

    # ── CustomerCommunication ────────────────────────────────
    op.create_table(
        'customer_communication',
        sa.Column('id',          sa.Integer(),      nullable=False),
        sa.Column('tenant_id',   sa.Integer(),      nullable=False),
        sa.Column('customer_id', sa.Integer(),      nullable=False),
        sa.Column('type',        sa.String(50),     nullable=False),
        sa.Column('subject',     sa.String(200),    nullable=True),
        sa.Column('sent_by',     sa.Integer(),      nullable=True),
        sa.Column('sent_at',     sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],   ['tenant.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sent_by'],     ['user.id'],     ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('customer_communication', schema=None) as batch_op:
        batch_op.create_index('ix_customer_comm_customer', ['customer_id'], unique=False)


def downgrade():
    with op.batch_alter_table('customer_communication', schema=None) as batch_op:
        batch_op.drop_index('ix_customer_comm_customer')
    op.drop_table('customer_communication')

    with op.batch_alter_table('customer_note', schema=None) as batch_op:
        batch_op.drop_index('ix_customer_note_customer')
    op.drop_table('customer_note')

    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.drop_column('created_at')
        batch_op.drop_column('notes')
        batch_op.drop_column('country')
        batch_op.drop_column('city')
        batch_op.drop_column('address')
        batch_op.drop_column('company')
