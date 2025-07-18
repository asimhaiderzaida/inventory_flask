"""Add po_number to PurchaseOrder

Revision ID: a28171c76ff3
Revises: 
Create Date: 2025-05-28 10:32:55.811359

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a28171c76ff3'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('purchase_order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('po_number', sa.String(length=50), nullable=True))
        batch_op.create_unique_constraint("uq_purchase_order_po_number", ['po_number'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('purchase_order', schema=None) as batch_op:
        batch_op.drop_constraint("uq_purchase_order_po_number", type_='unique')
        batch_op.drop_column('po_number')

    # ### end Alembic commands ###
