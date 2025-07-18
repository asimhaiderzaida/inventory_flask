"""Add unique constraint to username per tenant

Revision ID: c0dca89a8f79
Revises: 8a6e0396bce0
Create Date: 2025-06-28 11:35:16.644621

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c0dca89a8f79'
down_revision = '8a6e0396bce0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        # Skipping unique constraint 'uq_username_per_tenant' — already exists
        pass

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint('uq_username_per_tenant', type_='unique')

    # ### end Alembic commands ###
