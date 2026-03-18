"""add bin_id to part_stock and part_movement

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'o9p0q1r2s3t4'
down_revision = 'n8o9p0q1r2s3'
branch_labels = None
depends_on = None


def upgrade():
    # ── part_stock ────────────────────────────────────────────────────────────
    # 1. Add nullable bin_id column
    op.add_column('part_stock',
        sa.Column('bin_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_part_stock_bin_id', 'part_stock', 'bin',
        ['bin_id'], ['id'], ondelete='SET NULL')

    # 2. Drop old single unique constraint (part_id, location_id)
    op.drop_constraint('uix_part_location', 'part_stock', type_='unique')

    # 3. Two partial unique indexes to correctly handle NULL bin_id in PostgreSQL
    op.create_index(
        'uix_part_stock_no_bin',
        'part_stock', ['part_id', 'location_id'],
        unique=True,
        postgresql_where=sa.text('bin_id IS NULL'),
    )
    op.create_index(
        'uix_part_stock_with_bin',
        'part_stock', ['part_id', 'location_id', 'bin_id'],
        unique=True,
        postgresql_where=sa.text('bin_id IS NOT NULL'),
    )

    # ── part_movement ─────────────────────────────────────────────────────────
    op.add_column('part_movement',
        sa.Column('from_bin_id', sa.Integer(), nullable=True))
    op.add_column('part_movement',
        sa.Column('to_bin_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_part_movement_from_bin', 'part_movement', 'bin',
        ['from_bin_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(
        'fk_part_movement_to_bin', 'part_movement', 'bin',
        ['to_bin_id'], ['id'], ondelete='SET NULL')


def downgrade():
    # part_movement
    op.drop_constraint('fk_part_movement_to_bin',   'part_movement', type_='foreignkey')
    op.drop_constraint('fk_part_movement_from_bin', 'part_movement', type_='foreignkey')
    op.drop_column('part_movement', 'to_bin_id')
    op.drop_column('part_movement', 'from_bin_id')

    # part_stock — restore old constraint, drop partial indexes, drop column
    op.drop_index('uix_part_stock_with_bin', table_name='part_stock')
    op.drop_index('uix_part_stock_no_bin',   table_name='part_stock')
    op.drop_constraint('fk_part_stock_bin_id', 'part_stock', type_='foreignkey')
    op.drop_column('part_stock', 'bin_id')
    op.create_unique_constraint('uix_part_location', 'part_stock', ['part_id', 'location_id'])
