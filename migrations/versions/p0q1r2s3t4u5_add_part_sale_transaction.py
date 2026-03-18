"""add part_sale_transaction and part_sale_item tables; add parts_balance to customer

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'p0q1r2s3t4u5'
down_revision = 'o9p0q1r2s3t4'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Add parts_balance to customer
    conn.execute(sa.text(
        "ALTER TABLE customer ADD COLUMN IF NOT EXISTS parts_balance NUMERIC(10,2) NOT NULL DEFAULT 0"
    ))

    # Create part_sale_transaction
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS part_sale_transaction (
            id               SERIAL PRIMARY KEY,
            invoice_number   VARCHAR(20) NOT NULL,
            customer_id      INTEGER REFERENCES customer(id) ON DELETE SET NULL,
            customer_name    VARCHAR(128),
            sale_id          INTEGER REFERENCES sale_transaction(id) ON DELETE SET NULL,
            payment_method   VARCHAR(16) NOT NULL DEFAULT 'cash',
            payment_status   VARCHAR(16) NOT NULL DEFAULT 'paid',
            subtotal         NUMERIC(10,2) NOT NULL,
            tax              NUMERIC(10,2) NOT NULL DEFAULT 0,
            total_amount     NUMERIC(10,2) NOT NULL,
            notes            TEXT,
            sold_by          INTEGER REFERENCES "user"(id) ON DELETE SET NULL,
            sold_at          TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            tenant_id        INTEGER NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            CONSTRAINT uix_part_invoice_tenant UNIQUE (invoice_number, tenant_id)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_pst_tenant_date ON part_sale_transaction(tenant_id, sold_at)"
    ))

    # Create part_sale_item
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS part_sale_item (
            id               SERIAL PRIMARY KEY,
            transaction_id   INTEGER NOT NULL REFERENCES part_sale_transaction(id) ON DELETE CASCADE,
            part_id          INTEGER NOT NULL REFERENCES part(id) ON DELETE CASCADE,
            bin_id           INTEGER REFERENCES bin(id) ON DELETE SET NULL,
            location_id      INTEGER REFERENCES location(id) ON DELETE SET NULL,
            quantity         INTEGER NOT NULL,
            unit_price       NUMERIC(10,2) NOT NULL,
            subtotal         NUMERIC(10,2) NOT NULL,
            tenant_id        INTEGER NOT NULL REFERENCES tenant(id) ON DELETE CASCADE
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_psi_transaction_id ON part_sale_item(transaction_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_psi_part_id ON part_sale_item(part_id)"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS part_sale_item"))
    conn.execute(sa.text("DROP TABLE IF EXISTS part_sale_transaction"))
    conn.execute(sa.text("ALTER TABLE customer DROP COLUMN IF EXISTS parts_balance"))
