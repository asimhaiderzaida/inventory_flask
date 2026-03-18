"""Backfill NULL invoice_numbers on existing invoices

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

revision = 'r2s3t4u5v6w7'
down_revision = 'q1r2s3t4u5v6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE invoice
        SET invoice_number = CONCAT('INV-', LPAD(id::text, 5, '0'))
        WHERE invoice_number IS NULL
    """))


def downgrade():
    # Downgrade is a no-op — we don't want to re-null invoice_numbers
    pass
