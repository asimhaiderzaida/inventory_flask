"""add barcode field to part

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'q1r2s3t4u5v6'
down_revision = 'p0q1r2s3t4u5'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Add barcode column (nullable, max 100 chars)
    conn.execute(sa.text(
        "ALTER TABLE part ADD COLUMN IF NOT EXISTS barcode VARCHAR(100)"
    ))
    # Plain index for fast barcode lookups
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_part_barcode ON part (barcode)"
    ))
    # Partial unique index: enforces uniqueness only for non-null barcodes per tenant
    # Allows multiple parts with barcode=NULL in the same tenant
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uix_part_barcode_tenant "
        "ON part (barcode, tenant_id) WHERE barcode IS NOT NULL"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS uix_part_barcode_tenant"))
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_part_barcode"))
    conn.execute(sa.text("ALTER TABLE part DROP COLUMN IF EXISTS barcode"))
