"""Merge return model with existing migrations

Revision ID: d309e908ab03
Revises: 5ea8b84d0a03, edd27c7e99ef
Create Date: 2025-07-05 10:42:27.851207

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd309e908ab03'
down_revision = ('5ea8b84d0a03', 'edd27c7e99ef')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
