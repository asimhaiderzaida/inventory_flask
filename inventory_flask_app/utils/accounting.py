"""
Accounting utility helpers.

Shared between routes/accounting.py, routes/sales.py, routes/stock.py.
All functions expect to be called inside an active Flask app context.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal

from inventory_flask_app.models import (
    db,
    ExpenseCategory, EXPENSE_CATEGORY_DEFAULTS,
    Expense, AccountReceivable,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Category seeding
# ─────────────────────────────────────────────────────────────

def seed_expense_categories(tenant_id: int) -> None:
    """Ensure all default expense categories exist for this tenant.

    Idempotent — safe to call on every request; no-ops if already seeded.
    Only inserts rows that are missing (identified by slug).
    """
    existing_slugs = {
        row.slug
        for row in ExpenseCategory.query.filter_by(tenant_id=tenant_id).all()
    }
    added = False
    for name, slug, icon in EXPENSE_CATEGORY_DEFAULTS:
        if slug not in existing_slugs:
            db.session.add(ExpenseCategory(
                name=name, slug=slug, icon=icon, tenant_id=tenant_id
            ))
            added = True
    if added:
        db.session.commit()
        logger.info("Seeded expense categories for tenant %s", tenant_id)


def get_category_by_slug(slug: str, tenant_id: int) -> ExpenseCategory | None:
    """Return a category by slug, seeding defaults first if needed."""
    cat = ExpenseCategory.query.filter_by(slug=slug, tenant_id=tenant_id).first()
    if cat is None:
        seed_expense_categories(tenant_id)
        cat = ExpenseCategory.query.filter_by(slug=slug, tenant_id=tenant_id).first()
    return cat


# ─────────────────────────────────────────────────────────────
# AR helpers
# ─────────────────────────────────────────────────────────────

def create_ar_record(
    invoice,
    order,
    customer,
    tenant_id: int,
    amount_due: float,
    currency: str = 'AED',
    due_days: int = 30,
) -> AccountReceivable:
    """Create (and db.session.add) an AccountReceivable for a credit sale.

    Does NOT commit — caller is responsible for commit.

    Args:
        invoice:    Invoice ORM object (must already have .id via flush)
        order:      Order ORM object (must already have .id via flush)
        customer:   Customer ORM object
        tenant_id:  current tenant
        amount_due: pre-computed grand total including VAT
        currency:   3-letter currency code
        due_days:   days until due date (default 30)
    Returns:
        The new AccountReceivable (not yet committed).
    """
    # Guard: don't double-create if one already exists for this invoice
    existing = AccountReceivable.query.filter_by(
        invoice_id=invoice.id, tenant_id=tenant_id
    ).first()
    if existing:
        logger.warning(
            "AR already exists for invoice %s (tenant %s) — skipping",
            invoice.id, tenant_id
        )
        return existing

    ar = AccountReceivable(
        tenant_id=tenant_id,
        customer_id=customer.id,
        invoice_id=invoice.id,
        sale_id=order.id if order else None,
        amount_due=Decimal(str(round(amount_due, 2))),
        amount_paid=Decimal('0'),
        currency=currency,
        due_date=date.today() + timedelta(days=due_days),
        status='open',
    )
    db.session.add(ar)
    logger.info(
        "AR created: customer=%s invoice=%s amount=%.2f due=%s",
        customer.id, invoice.id, amount_due, ar.due_date,
    )
    return ar


def recalculate_ar_status(ar: AccountReceivable) -> None:
    """Update ar.status based on amount_paid vs amount_due and due_date.

    Does NOT commit — caller responsible.
    """
    paid  = float(ar.amount_paid or 0)
    due   = float(ar.amount_due  or 0)
    today = date.today()

    if ar.status == 'written_off':
        return  # never auto-change written_off

    if paid >= due:
        ar.status = 'paid'
    elif paid > 0:
        ar.status = 'partial'
    elif ar.due_date and ar.due_date < today:
        ar.status = 'overdue'
    else:
        ar.status = 'open'


# ─────────────────────────────────────────────────────────────
# PO expense auto-creation
# ─────────────────────────────────────────────────────────────

def create_po_expense(po, tenant_id: int, created_by_user_id: int | None = None) -> Expense | None:
    """Auto-create an Expense record when a PO is fully received.

    Skips creation if an expense already exists for this PO.
    Does NOT commit — caller responsible.

    Returns the new Expense, or None if skipped.
    """
    # Guard: one expense per PO
    existing = Expense.query.filter_by(po_id=po.id, tenant_id=tenant_id, deleted_at=None).first()
    if existing:
        logger.debug("Expense already exists for PO %s — skipping", po.id)
        return existing

    cat = get_category_by_slug('stock-purchases', tenant_id)

    # PurchaseOrderItem has no unit cost column yet — create a AED 0 placeholder
    # the user can edit the amount on the Expense edit page.
    expense = Expense(
        tenant_id=tenant_id,
        category_id=cat.id if cat else None,
        amount=Decimal('0.00'),
        currency='AED',
        description=f"Stock purchase — PO #{po.po_number}",
        reference=po.po_number,
        expense_date=date.today(),
        payment_method='bank_transfer',
        vendor_id=po.vendor_id if po.vendor_id else None,
        po_id=po.id,
        notes=(
            "Auto-created when PO was marked received. "
            "Update the amount to reflect the actual purchase cost."
        ),
        created_by=created_by_user_id,
    )
    db.session.add(expense)
    logger.info(
        "Expense auto-created for PO %s (tenant %s)", po.po_number, tenant_id
    )
    return expense


# ─────────────────────────────────────────────────────────────
# P&L helpers used by report routes
# ─────────────────────────────────────────────────────────────

def get_currency(tenant_id: int) -> str:
    """Return the tenant's configured currency (default AED)."""
    from inventory_flask_app.models import TenantSettings
    s = TenantSettings.query.filter_by(tenant_id=tenant_id, key='currency').first()
    return (s.value or 'AED') if s else 'AED'
