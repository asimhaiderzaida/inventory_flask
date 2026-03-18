"""Add first-class Bin model and migrate shelf_bin data

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-03-11 16:00:00.000000

Changes:
  - CREATE TABLE bin (id, name, location_id, description, tenant_id, created_at)
  - ADD COLUMN product_instance.bin_id FK → bin.id
  - Data migration: for each unique (shelf_bin, location_id, tenant_id) in
    product_instance, create a Bin row and back-fill bin_id on all matching instances.
"""
from alembic import op
import sqlalchemy as sa

revision = 'j4k5l6m7n8o9'
down_revision = 'i3j4k5l6m7n8'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── 1. Create bin table ────────────────────────────────────────────────────
    op.create_table(
        'bin',
        sa.Column('id',          sa.Integer(),     nullable=False),
        sa.Column('name',        sa.String(64),    nullable=False),
        sa.Column('location_id', sa.Integer(),     nullable=False),
        sa.Column('description', sa.String(255),   nullable=True),
        sa.Column('tenant_id',   sa.Integer(),     nullable=False),
        sa.Column('created_at',  sa.DateTime(),    nullable=True),
        sa.ForeignKeyConstraint(['location_id'], ['location.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'],   ['tenant.id'],   ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'location_id', 'tenant_id',
                            name='uq_bin_name_location_tenant'),
    )
    with op.batch_alter_table('bin', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bin_name'), ['name'], unique=False)

    # ── 2. Add bin_id column to product_instance ───────────────────────────────
    conn.execute(sa.text(
        "ALTER TABLE product_instance "
        "ADD COLUMN IF NOT EXISTS bin_id INTEGER REFERENCES bin(id) ON DELETE SET NULL"
    ))

    # ── 3. Data migration: promote shelf_bin strings → Bin rows ───────────────
    # Fetch all unique (shelf_bin, location_id, tenant_id) combos that have data
    rows = conn.execute(sa.text("""
        SELECT DISTINCT
            pi.shelf_bin,
            pi.location_id,
            p.tenant_id
        FROM product_instance pi
        JOIN product p ON p.id = pi.product_id
        WHERE pi.shelf_bin IS NOT NULL
          AND pi.shelf_bin <> ''
          AND pi.location_id IS NOT NULL
    """)).fetchall()

    from datetime import datetime
    now = datetime.utcnow()

    for shelf_bin, location_id, tenant_id in rows:
        # Insert bin if not already present (idempotent)
        conn.execute(sa.text("""
            INSERT INTO bin (name, location_id, tenant_id, created_at)
            VALUES (:name, :location_id, :tenant_id, :created_at)
            ON CONFLICT ON CONSTRAINT uq_bin_name_location_tenant DO NOTHING
        """), {'name': shelf_bin.upper(), 'location_id': location_id,
               'tenant_id': tenant_id, 'created_at': now})

    # ── 4. Back-fill bin_id on existing product_instance rows ─────────────────
    conn.execute(sa.text("""
        UPDATE product_instance
        SET bin_id = b.id
        FROM bin b
        JOIN product p ON p.tenant_id = b.tenant_id
        WHERE b.name            = product_instance.shelf_bin
          AND b.location_id     = product_instance.location_id
          AND p.id              = product_instance.product_id
          AND product_instance.shelf_bin IS NOT NULL
          AND product_instance.shelf_bin  <> ''
    """))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "ALTER TABLE product_instance DROP COLUMN IF EXISTS bin_id"
    ))
    op.drop_table('bin')
