"""Change location.name unique constraint from global to per-tenant

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-03-11 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'i3j4k5l6m7n8'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Drop old global unique constraint (various possible names)
    conn.execute(sa.text(
        "ALTER TABLE location DROP CONSTRAINT IF EXISTS location_name_key"
    ))
    conn.execute(sa.text(
        "ALTER TABLE location DROP CONSTRAINT IF EXISTS uq_location_name"
    ))

    # Drop old unique index if it exists
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_location_name"))

    # Re-create index as non-unique
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_location_name ON location (name)"))

    # Add per-tenant unique constraint
    conn.execute(sa.text(
        "ALTER TABLE location DROP CONSTRAINT IF EXISTS uq_location_name_per_tenant"
    ))
    conn.execute(sa.text(
        "ALTER TABLE location ADD CONSTRAINT uq_location_name_per_tenant "
        "UNIQUE (name, tenant_id)"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "ALTER TABLE location DROP CONSTRAINT IF EXISTS uq_location_name_per_tenant"
    ))
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_location_name"))
    conn.execute(sa.text("CREATE UNIQUE INDEX ix_location_name ON location (name)"))
