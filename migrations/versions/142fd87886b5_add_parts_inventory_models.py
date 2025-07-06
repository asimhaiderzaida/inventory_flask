"""add parts inventory models"""

revision = '142fd87886b5'
down_revision = 'edd27c7e99ef'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    with op.batch_alter_table('product_instance', schema=None) as batch_op:
        # Skipping column creation because 'shelf_bin' already exists
        pass

def downgrade():
    with op.batch_alter_table('product_instance', schema=None) as batch_op:
        batch_op.drop_column('shelf_bin')
