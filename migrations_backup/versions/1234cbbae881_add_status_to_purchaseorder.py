"""Add status to PurchaseOrder

Revision ID: 1234cbbae881
Revises: 2b1ad29d4b1e
Create Date: 2025-06-08 04:17:09.702585

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1234cbbae881'
down_revision = '2b1ad29d4b1e'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('purchase_order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('purchase_order', schema=None) as batch_op:
        batch_op.drop_column('status')

    # ### end Alembic commands ###
