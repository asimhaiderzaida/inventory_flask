"""Parts Phase 1 — fix part_number uniqueness and add vendor_id FK

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-03-12 00:00:00.000000

Changes:
  - DROP global unique constraint on part.part_number
  - ADD compound unique constraint (part_number, tenant_id)
  - ADD COLUMN part.vendor_id FK → vendor.id ON DELETE SET NULL
"""
from alembic import op
import sqlalchemy as sa

revision = 'k5l6m7n8o9p0'
down_revision = 'j4k5l6m7n8o9'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. Add vendor_id column (nullable FK → vendor)
    conn.execute(sa.text(
        "ALTER TABLE part "
        "ADD COLUMN IF NOT EXISTS vendor_id INTEGER "
        "REFERENCES vendor(id) ON DELETE SET NULL"
    ))

    # 2. Drop the old global unique constraint on part_number.
    #    PostgreSQL auto-names it <table>_<col>_key.
    conn.execute(sa.text(
        "ALTER TABLE part DROP CONSTRAINT IF EXISTS part_part_number_key"
    ))

    # 3. Add compound unique constraint (part_number, tenant_id)
    conn.execute(sa.text(
        "ALTER TABLE part "
        "ADD CONSTRAINT uix_part_number_tenant UNIQUE (part_number, tenant_id)"
    ))


def downgrade():
    conn = op.get_bind()

    conn.execute(sa.text(
        "ALTER TABLE part DROP CONSTRAINT IF EXISTS uix_part_number_tenant"
    ))
    conn.execute(sa.text(
        "ALTER TABLE part ADD CONSTRAINT part_part_number_key UNIQUE (part_number)"
    ))
    conn.execute(sa.text(
        "ALTER TABLE part DROP COLUMN IF EXISTS vendor_id"
    ))
