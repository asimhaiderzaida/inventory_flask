"""Rebuild PO system: PurchaseOrderItem, PO location/status/notes fixes

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-03-11 14:00:00.000000

Changes:
  - purchase_order: add location_id, notes; fix vendor FK to SET NULL;
    make po_number NOT NULL; add 'partial'/'cancelled' status values
  - CREATE TABLE purchase_order_item
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'h2i3j4k5l6m7'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── purchase_order: fix vendor FK (CASCADE → SET NULL, nullable) ──────────
    # Drop old FK constraint (name may vary; use named constraint if present)
    try:
        op.drop_constraint('purchase_order_vendor_id_fkey', 'purchase_order', type_='foreignkey')
    except Exception:
        # Fallback: find and drop by convention
        result = conn.execute(sa.text(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_name='purchase_order' AND constraint_type='FOREIGN KEY' "
            "AND constraint_name LIKE '%vendor%'"
        )).fetchone()
        if result:
            op.drop_constraint(result[0], 'purchase_order', type_='foreignkey')

    # Make vendor_id nullable
    op.alter_column('purchase_order', 'vendor_id', nullable=True)

    # Re-create FK with SET NULL
    op.create_foreign_key(
        'purchase_order_vendor_id_fkey',
        'purchase_order', 'vendor',
        ['vendor_id'], ['id'],
        ondelete='SET NULL'
    )

    # ── purchase_order: make po_number NOT NULL ───────────────────────────────
    # First give any NULLs a placeholder value
    conn.execute(sa.text(
        "UPDATE purchase_order SET po_number = 'PO-LEGACY-' || id::text WHERE po_number IS NULL"
    ))
    op.alter_column('purchase_order', 'po_number', nullable=False)

    # ── purchase_order: add location_id column ────────────────────────────────
    op.add_column('purchase_order', sa.Column('location_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'purchase_order_location_id_fkey',
        'purchase_order', 'location',
        ['location_id'], ['id'],
        ondelete='SET NULL'
    )

    # ── purchase_order: add notes column ─────────────────────────────────────
    op.add_column('purchase_order', sa.Column('notes', sa.Text(), nullable=True))

    # ── CREATE purchase_order_item ────────────────────────────────────────────
    op.create_table(
        'purchase_order_item',
        sa.Column('id',          sa.Integer(),     primary_key=True),
        sa.Column('po_id',       sa.Integer(),     sa.ForeignKey('purchase_order.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id',   sa.Integer(),     sa.ForeignKey('tenant.id',         ondelete='CASCADE'), nullable=False),
        sa.Column('serial',      sa.String(100),   nullable=False),
        sa.Column('asset_tag',   sa.String(100),   nullable=True),
        sa.Column('item_name',   sa.String(100),   nullable=True),
        sa.Column('make',        sa.String(100),   nullable=True),
        sa.Column('model',       sa.String(100),   nullable=True),
        sa.Column('display',     sa.String(100),   nullable=True),
        sa.Column('cpu',         sa.String(100),   nullable=True),
        sa.Column('ram',         sa.String(100),   nullable=True),
        sa.Column('gpu1',        sa.String(100),   nullable=True),
        sa.Column('gpu2',        sa.String(100),   nullable=True),
        sa.Column('grade',       sa.String(20),    nullable=True),
        sa.Column('disk1size',   sa.String(100),   nullable=True),
        sa.Column('location_id', sa.Integer(),     sa.ForeignKey('location.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status',      sa.String(20),    nullable=False, server_default='expected'),
        sa.Column('received_at', sa.DateTime(),    nullable=True),
        sa.Column('notes',       sa.Text(),        nullable=True),
    )
    op.create_index('ix_poi_serial',    'purchase_order_item', ['serial'])
    op.create_index('ix_poi_asset_tag', 'purchase_order_item', ['asset_tag'])
    op.create_index('ix_poi_po_id',     'purchase_order_item', ['po_id'])


def downgrade():
    op.drop_table('purchase_order_item')
    op.drop_column('purchase_order', 'notes')
    op.drop_constraint('purchase_order_location_id_fkey', 'purchase_order', type_='foreignkey')
    op.drop_column('purchase_order', 'location_id')

    # Restore vendor FK to CASCADE (nullable=False)
    op.drop_constraint('purchase_order_vendor_id_fkey', 'purchase_order', type_='foreignkey')
    op.alter_column('purchase_order', 'vendor_id', nullable=False)
    op.create_foreign_key(
        'purchase_order_vendor_id_fkey',
        'purchase_order', 'vendor',
        ['vendor_id'], ['id'],
        ondelete='CASCADE'
    )
    op.alter_column('purchase_order', 'po_number', nullable=True)
