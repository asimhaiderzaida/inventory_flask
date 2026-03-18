"""add part_usage table

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'm7n8o9p0q1r2'
down_revision = 'l6m7n8o9p0q1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS part_usage (
            id          SERIAL PRIMARY KEY,
            part_id     INTEGER NOT NULL REFERENCES part(id) ON DELETE CASCADE,
            instance_id INTEGER REFERENCES product_instance(id) ON DELETE SET NULL,
            quantity    INTEGER NOT NULL,
            used_by     INTEGER REFERENCES "user"(id) ON DELETE SET NULL,
            used_at     TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            note        VARCHAR(256),
            tenant_id   INTEGER NOT NULL REFERENCES tenant(id) ON DELETE CASCADE
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_part_usage_part_id     ON part_usage(part_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_part_usage_instance_id ON part_usage(instance_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_part_usage_tenant_id   ON part_usage(tenant_id)"))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS part_usage"))
