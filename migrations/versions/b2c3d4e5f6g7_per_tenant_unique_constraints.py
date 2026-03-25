"""per_tenant_unique_constraints_and_indexes

Revision ID: b2c3d4e5f6g7
Revises: 1ae97b59bf00
Create Date: 2026-03-25 00:00:00.000000

Replace global unique constraints on serial/asset/po_number with
per-tenant composite unique constraints. Add missing performance
indexes on ProductInstance and TenantSettings unique constraint.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6g7'
down_revision = '1ae97b59bf00'
branch_labels = None
depends_on = None


def upgrade():
    # ── Product: drop global unique indexes, add per-tenant index ────────
    with op.batch_alter_table('product', schema=None) as batch_op:
        try:
            batch_op.drop_index('ix_product_serial')
        except Exception:
            pass
        try:
            batch_op.drop_index('ix_product_asset')
        except Exception:
            pass
        batch_op.create_index('ix_product_serial', ['serial'], unique=False)
        batch_op.create_index('ix_product_asset', ['asset'], unique=False)
        try:
            batch_op.create_index('ix_product_tenant_id', ['tenant_id'], unique=False)
        except Exception:
            pass

    # ── ProductInstance: drop global unique, add per-tenant constraints ──
    with op.batch_alter_table('product_instance', schema=None) as batch_op:
        try:
            batch_op.drop_index('ix_product_instance_serial')
        except Exception:
            pass
        try:
            batch_op.drop_index('ix_product_instance_asset')
        except Exception:
            pass
        batch_op.create_index('ix_product_instance_serial', ['serial'], unique=False)
        batch_op.create_index('ix_product_instance_asset', ['asset'], unique=False)
        try:
            batch_op.create_unique_constraint('uq_pi_serial_tenant', ['serial', 'tenant_id'])
        except Exception:
            pass
        try:
            batch_op.create_unique_constraint('uq_pi_asset_tenant', ['asset', 'tenant_id'])
        except Exception:
            pass
        # Performance indexes for commonly-queried columns
        try:
            batch_op.create_index('ix_pi_process_stage', ['process_stage'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index('ix_pi_location_id_perf', ['location_id'], unique=False)
        except Exception:
            pass
        try:
            batch_op.create_index('ix_pi_bin_id_perf', ['bin_id'], unique=False)
        except Exception:
            pass

    # ── PurchaseOrder: drop global unique, add per-tenant constraint ──────
    with op.batch_alter_table('purchase_order', schema=None) as batch_op:
        try:
            batch_op.drop_constraint('purchase_order_po_number_key', type_='unique')
        except Exception:
            try:
                batch_op.drop_index('purchase_order_po_number_key')
            except Exception:
                pass
        try:
            batch_op.create_unique_constraint('uq_po_number_tenant', ['po_number', 'tenant_id'])
        except Exception:
            pass

    # ── TenantSettings: unique constraint on (tenant_id, key) ────────────
    with op.batch_alter_table('tenant_settings', schema=None) as batch_op:
        try:
            batch_op.create_unique_constraint('uq_tenant_settings_key', ['tenant_id', 'key'])
        except Exception:
            pass


def downgrade():
    with op.batch_alter_table('tenant_settings', schema=None) as batch_op:
        try:
            batch_op.drop_constraint('uq_tenant_settings_key', type_='unique')
        except Exception:
            pass

    with op.batch_alter_table('purchase_order', schema=None) as batch_op:
        try:
            batch_op.drop_constraint('uq_po_number_tenant', type_='unique')
        except Exception:
            pass

    with op.batch_alter_table('product_instance', schema=None) as batch_op:
        try:
            batch_op.drop_constraint('uq_pi_asset_tenant', type_='unique')
        except Exception:
            pass
        try:
            batch_op.drop_constraint('uq_pi_serial_tenant', type_='unique')
        except Exception:
            pass
        try:
            batch_op.drop_index('ix_pi_bin_id_perf')
        except Exception:
            pass
        try:
            batch_op.drop_index('ix_pi_location_id_perf')
        except Exception:
            pass
        try:
            batch_op.drop_index('ix_pi_process_stage')
        except Exception:
            pass
        batch_op.drop_index('ix_product_instance_serial')
        batch_op.drop_index('ix_product_instance_asset')
        batch_op.create_index('ix_product_instance_serial', ['serial'], unique=True)
        batch_op.create_index('ix_product_instance_asset', ['asset'], unique=True)
