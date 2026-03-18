"""Parts Phase 2 — add instance_id to part_movement

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-03-12 00:01:00.000000

Changes:
  - ADD COLUMN part_movement.instance_id FK → product_instance.id ON DELETE SET NULL
"""
from alembic import op
import sqlalchemy as sa

revision = 'l6m7n8o9p0q1'
down_revision = 'k5l6m7n8o9p0'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "ALTER TABLE part_movement "
        "ADD COLUMN IF NOT EXISTS instance_id INTEGER "
        "REFERENCES product_instance(id) ON DELETE SET NULL"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "ALTER TABLE part_movement DROP COLUMN IF EXISTS instance_id"
    ))
