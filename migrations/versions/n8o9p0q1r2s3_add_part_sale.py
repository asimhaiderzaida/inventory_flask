"""add part_sale table

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'n8o9p0q1r2s3'
down_revision = 'm7n8o9p0q1r2'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS part_sale (
            id          SERIAL PRIMARY KEY,
            part_id     INTEGER NOT NULL REFERENCES part(id) ON DELETE CASCADE,
            location_id INTEGER REFERENCES location(id) ON DELETE SET NULL,
            customer_id INTEGER REFERENCES customer(id) ON DELETE SET NULL,
            quantity    INTEGER NOT NULL,
            unit_price  DOUBLE PRECISION,
            note        VARCHAR(256),
            sold_by     INTEGER REFERENCES "user"(id) ON DELETE SET NULL,
            sold_at     TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            tenant_id   INTEGER NOT NULL REFERENCES tenant(id) ON DELETE CASCADE
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_part_sale_part_id   ON part_sale(part_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_part_sale_tenant_id ON part_sale(tenant_id)"))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS part_sale"))
