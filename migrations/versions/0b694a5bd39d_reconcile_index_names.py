"""reconcile_index_names

Revision ID: 0b694a5bd39d
Revises: y1z2a3b4c5d6
Create Date: 2026-03-16 12:52:44.681927

Renames purchase_order_item indexes from short names (ix_poi_*)
to SQLAlchemy-standard names so flask db check passes.
Also: makes ix_part_part_number non-unique (uniqueness per-tenant is
already enforced by uix_part_number_tenant) and promotes the
username unique constraint to a unique index.
"""
from alembic import op
import sqlalchemy as sa


revision = '0b694a5bd39d'
down_revision = 'y1z2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    # ── purchase_order_item: rename short indexes to SQLAlchemy standard names ─
    with op.batch_alter_table('purchase_order_item', schema=None) as batch_op:
        batch_op.drop_index('ix_poi_asset_tag')
        batch_op.drop_index('ix_poi_serial')
        # Rename po_id index too (po_id is a FK, keep indexed)
        batch_op.drop_index('ix_poi_po_id')
        batch_op.create_index('ix_purchase_order_item_asset_tag', ['asset_tag'], unique=False)
        batch_op.create_index('ix_purchase_order_item_serial', ['serial'], unique=False)
        batch_op.create_index('ix_purchase_order_item_po_id', ['po_id'], unique=False)

    # ── part: part_number index should be non-unique (tenant-scoped uniqueness
    #    is already enforced by uix_part_number_tenant) ─────────────────────────
    with op.batch_alter_table('part', schema=None) as batch_op:
        batch_op.drop_index('ix_part_part_number')
        batch_op.create_index('ix_part_part_number', ['part_number'], unique=False)

    # ── user: drop named unique constraint, replace with unique index
    #    (net effect: username uniqueness maintained) ──────────────────────────
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint('uq_username_global', type_='unique')
        batch_op.drop_index('ix_user_username')
        batch_op.create_index('ix_user_username', ['username'], unique=True)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index('ix_user_username')
        batch_op.create_index('ix_user_username', ['username'], unique=False)
        batch_op.create_unique_constraint('uq_username_global', ['username'])

    with op.batch_alter_table('part', schema=None) as batch_op:
        batch_op.drop_index('ix_part_part_number')
        batch_op.create_index('ix_part_part_number', ['part_number'], unique=True)

    with op.batch_alter_table('purchase_order_item', schema=None) as batch_op:
        batch_op.drop_index('ix_purchase_order_item_po_id')
        batch_op.drop_index('ix_purchase_order_item_serial')
        batch_op.drop_index('ix_purchase_order_item_asset_tag')
        batch_op.create_index('ix_poi_serial', ['serial'], unique=False)
        batch_op.create_index('ix_poi_po_id', ['po_id'], unique=False)
        batch_op.create_index('ix_poi_asset_tag', ['asset_tag'], unique=False)
