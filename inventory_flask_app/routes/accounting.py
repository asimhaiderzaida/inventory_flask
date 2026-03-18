"""
Accounting module: Expenses, Accounts Receivable, Other Income,
P&L, Cash Flow, AR Aging, Category management.
Only admins and supervisors can access these routes.
"""
import csv
import io
import logging
from calendar import month_abbr
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, Response
from flask_login import login_required, current_user
from sqlalchemy import func, extract

from inventory_flask_app.models import (
    db,
    ExpenseCategory, Expense, AccountReceivable, ARPayment, OtherIncome,
    Customer, Vendor, PurchaseOrder,
    SaleTransaction, SaleItem, ProductInstance, Product,
    PartSaleTransaction,
)
from inventory_flask_app.utils.accounting import (
    seed_expense_categories, recalculate_ar_status, get_currency,
)

logger = logging.getLogger(__name__)

accounting_bp = Blueprint('accounting_bp', __name__, url_prefix='/accounting')

PAYMENT_METHODS = [
    ('cash',          'Cash'),
    ('card',          'Card'),
    ('bank_transfer', 'Bank Transfer'),
    ('cheque',        'Cheque'),
    ('other',         'Other'),
]


def _require_accounting():
    if current_user.role != 'admin':
        abort(403)


def _tid():
    return current_user.tenant_id


# ─────────────────────────────────────────────────────────────
# Dashboard / overview
# ─────────────────────────────────────────────────────────────

@accounting_bp.route('/')
@login_required
def index():
    _require_accounting()
    tid = _tid()
    today = date.today()
    month_start = today.replace(day=1)

    # MTD expenses
    mtd_expenses = db.session.query(
        func.coalesce(func.sum(Expense.amount), 0)
    ).filter(
        Expense.tenant_id == tid,
        Expense.deleted_at.is_(None),
        Expense.expense_date >= month_start,
    ).scalar() or 0

    # Expenses by category (all time, not deleted)
    cat_rows = db.session.query(
        ExpenseCategory.name,
        ExpenseCategory.icon,
        func.coalesce(func.sum(Expense.amount), 0).label('total'),
    ).outerjoin(
        Expense,
        (Expense.category_id == ExpenseCategory.id) & (Expense.deleted_at.is_(None))
    ).filter(
        ExpenseCategory.tenant_id == tid,
    ).group_by(ExpenseCategory.id).order_by(func.sum(Expense.amount).desc().nullslast()).all()

    # AR summary
    ar_open = db.session.query(
        func.coalesce(func.sum(AccountReceivable.amount_due - AccountReceivable.amount_paid), 0)
    ).filter(
        AccountReceivable.tenant_id == tid,
        AccountReceivable.status.in_(('open', 'partial', 'overdue')),
    ).scalar() or 0

    ar_overdue_count = AccountReceivable.query.filter_by(tenant_id=tid, status='overdue').count()

    # MTD other income
    mtd_income = db.session.query(
        func.coalesce(func.sum(OtherIncome.amount), 0)
    ).filter(
        OtherIncome.tenant_id == tid,
        OtherIncome.deleted_at.is_(None),
        OtherIncome.income_date >= month_start,
    ).scalar() or 0

    # Recent expenses (last 10)
    recent_expenses = (
        Expense.query
        .filter_by(tenant_id=tid)
        .filter(Expense.deleted_at.is_(None))
        .order_by(Expense.expense_date.desc(), Expense.id.desc())
        .limit(10).all()
    )

    currency = get_currency(tid)
    seed_expense_categories(tid)

    return render_template(
        'accounting/index.html',
        mtd_expenses=float(mtd_expenses),
        ar_open=float(ar_open),
        ar_overdue_count=ar_overdue_count,
        mtd_income=float(mtd_income),
        cat_rows=cat_rows,
        recent_expenses=recent_expenses,
        currency=currency,
        today=today,
    )


# ─────────────────────────────────────────────────────────────
# Expenses
# ─────────────────────────────────────────────────────────────

@accounting_bp.route('/expenses')
@login_required
def expenses():
    _require_accounting()
    tid = _tid()
    seed_expense_categories(tid)

    # Filters
    cat_id   = request.args.get('category', type=int)
    method   = request.args.get('method', '')
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')

    q = Expense.query.filter_by(tenant_id=tid).filter(Expense.deleted_at.is_(None))
    if cat_id:
        q = q.filter(Expense.category_id == cat_id)
    if method:
        q = q.filter(Expense.payment_method == method)
    if date_from:
        try:
            q = q.filter(Expense.expense_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(Expense.expense_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            pass

    expenses_list = q.order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    total = sum(float(e.amount) for e in expenses_list)

    categories = ExpenseCategory.query.filter_by(tenant_id=tid).order_by(ExpenseCategory.name).all()
    currency = get_currency(tid)

    return render_template(
        'accounting/expenses.html',
        expenses=expenses_list,
        total=total,
        categories=categories,
        payment_methods=PAYMENT_METHODS,
        currency=currency,
        filter_cat=cat_id,
        filter_method=method,
        filter_date_from=date_from,
        filter_date_to=date_to,
    )


@accounting_bp.route('/expenses/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    _require_accounting()
    tid = _tid()
    seed_expense_categories(tid)
    categories = ExpenseCategory.query.filter_by(tenant_id=tid).order_by(ExpenseCategory.name).all()
    vendors    = Vendor.query.filter_by(tenant_id=tid).order_by(Vendor.name).all()
    currency   = get_currency(tid)

    if request.method == 'POST':
        try:
            amount = Decimal(request.form['amount'].strip())
        except (InvalidOperation, KeyError):
            flash('Invalid amount.', 'danger')
            return redirect(request.url)

        desc = request.form.get('description', '').strip()
        if not desc:
            flash('Description is required.', 'danger')
            return redirect(request.url)

        try:
            exp_date = datetime.strptime(request.form['expense_date'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            flash('Invalid date.', 'danger')
            return redirect(request.url)

        cat_id_raw  = request.form.get('category_id') or None
        vendor_raw  = request.form.get('vendor_id') or None
        po_raw      = request.form.get('po_id') or None

        expense = Expense(
            tenant_id      = tid,
            category_id    = int(cat_id_raw) if cat_id_raw else None,
            amount         = amount,
            currency       = currency,
            description    = desc,
            reference      = request.form.get('reference', '').strip() or None,
            expense_date   = exp_date,
            payment_method = request.form.get('payment_method', 'cash'),
            vendor_id      = int(vendor_raw) if vendor_raw else None,
            po_id          = int(po_raw) if po_raw else None,
            notes          = request.form.get('notes', '').strip() or None,
            created_by     = current_user.id,
        )
        db.session.add(expense)
        db.session.commit()
        flash('Expense recorded.', 'success')
        return redirect(url_for('accounting_bp.expenses'))

    return render_template(
        'accounting/add_expense.html',
        categories=categories,
        vendors=vendors,
        payment_methods=PAYMENT_METHODS,
        currency=currency,
        today=date.today().isoformat(),
        expense=None,
    )


@accounting_bp.route('/expenses/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    _require_accounting()
    tid = _tid()
    expense = Expense.query.filter_by(id=expense_id, tenant_id=tid).first_or_404()
    seed_expense_categories(tid)
    categories = ExpenseCategory.query.filter_by(tenant_id=tid).order_by(ExpenseCategory.name).all()
    vendors    = Vendor.query.filter_by(tenant_id=tid).order_by(Vendor.name).all()
    currency   = get_currency(tid)

    if request.method == 'POST':
        try:
            expense.amount = Decimal(request.form['amount'].strip())
        except (InvalidOperation, KeyError):
            flash('Invalid amount.', 'danger')
            return redirect(request.url)

        desc = request.form.get('description', '').strip()
        if not desc:
            flash('Description is required.', 'danger')
            return redirect(request.url)

        try:
            expense.expense_date = datetime.strptime(request.form['expense_date'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            flash('Invalid date.', 'danger')
            return redirect(request.url)

        cat_id_raw = request.form.get('category_id') or None
        vendor_raw = request.form.get('vendor_id') or None

        expense.description    = desc
        expense.category_id    = int(cat_id_raw) if cat_id_raw else None
        expense.vendor_id      = int(vendor_raw) if vendor_raw else None
        expense.reference      = request.form.get('reference', '').strip() or None
        expense.payment_method = request.form.get('payment_method', 'cash')
        expense.notes          = request.form.get('notes', '').strip() or None

        db.session.commit()
        flash('Expense updated.', 'success')
        return redirect(url_for('accounting_bp.expenses'))

    return render_template(
        'accounting/add_expense.html',
        categories=categories,
        vendors=vendors,
        payment_methods=PAYMENT_METHODS,
        currency=currency,
        today=date.today().isoformat(),
        expense=expense,
    )


@accounting_bp.route('/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete_expense(expense_id):
    _require_accounting()
    tid = _tid()
    expense = Expense.query.filter_by(id=expense_id, tenant_id=tid).first_or_404()
    expense.deleted_at = datetime.utcnow()
    db.session.commit()
    flash('Expense deleted.', 'success')
    return redirect(url_for('accounting_bp.expenses'))


# ─────────────────────────────────────────────────────────────
# Accounts Receivable
# ─────────────────────────────────────────────────────────────

@accounting_bp.route('/receivables')
@login_required
def receivables():
    _require_accounting()
    tid = _tid()

    status_filter = request.args.get('status', '')
    q = AccountReceivable.query.filter_by(tenant_id=tid)
    if status_filter:
        q = q.filter(AccountReceivable.status == status_filter)
    else:
        # Default: exclude fully paid & written off
        q = q.filter(AccountReceivable.status.in_(('open', 'partial', 'overdue')))

    ar_list = q.order_by(AccountReceivable.due_date.asc().nullslast(), AccountReceivable.id.desc()).all()
    total_outstanding = sum(ar.balance for ar in ar_list)
    currency = get_currency(tid)

    return render_template(
        'accounting/receivables.html',
        ar_list=ar_list,
        total_outstanding=total_outstanding,
        currency=currency,
        status_filter=status_filter,
    )


@accounting_bp.route('/receivables/<int:ar_id>')
@login_required
def ar_detail(ar_id):
    _require_accounting()
    tid = _tid()
    ar = AccountReceivable.query.filter_by(id=ar_id, tenant_id=tid).first_or_404()
    currency = get_currency(tid)
    return render_template(
        'accounting/ar_detail.html',
        ar=ar,
        currency=currency,
        payment_methods=PAYMENT_METHODS,
        today=date.today().isoformat(),
    )


@accounting_bp.route('/receivables/<int:ar_id>/payment', methods=['POST'])
@login_required
def record_payment(ar_id):
    _require_accounting()
    tid = _tid()
    ar = AccountReceivable.query.filter_by(id=ar_id, tenant_id=tid).first_or_404()

    try:
        amount = Decimal(request.form['amount'].strip())
        if amount <= 0:
            raise ValueError
    except (InvalidOperation, ValueError, KeyError):
        flash('Invalid payment amount.', 'danger')
        return redirect(url_for('accounting_bp.ar_detail', ar_id=ar_id))

    try:
        pay_date = datetime.strptime(request.form['payment_date'], '%Y-%m-%d').date()
    except (ValueError, KeyError):
        flash('Invalid payment date.', 'danger')
        return redirect(url_for('accounting_bp.ar_detail', ar_id=ar_id))

    payment = ARPayment(
        tenant_id      = tid,
        ar_id          = ar.id,
        amount         = amount,
        payment_method = request.form.get('payment_method', 'cash'),
        payment_date   = pay_date,
        reference      = request.form.get('reference', '').strip() or None,
        notes          = request.form.get('notes', '').strip() or None,
        recorded_by    = current_user.id,
    )
    db.session.add(payment)

    ar.amount_paid = (ar.amount_paid or Decimal('0')) + amount
    recalculate_ar_status(ar)
    db.session.commit()

    flash(f'Payment of {float(amount):,.2f} recorded.', 'success')
    return redirect(url_for('accounting_bp.ar_detail', ar_id=ar_id))


@accounting_bp.route('/receivables/<int:ar_id>/write-off', methods=['POST'])
@login_required
def write_off_ar(ar_id):
    _require_accounting()
    tid = _tid()
    if current_user.role != 'admin':
        abort(403)
    ar = AccountReceivable.query.filter_by(id=ar_id, tenant_id=tid).first_or_404()
    ar.status = 'written_off'
    ar.notes = (ar.notes or '') + f'\n[Written off on {date.today()} by {current_user.username}]'
    db.session.commit()
    flash('AR record written off.', 'warning')
    return redirect(url_for('accounting_bp.receivables'))


# ─────────────────────────────────────────────────────────────
# Other Income
# ─────────────────────────────────────────────────────────────

@accounting_bp.route('/income')
@login_required
def income():
    _require_accounting()
    tid = _tid()

    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')

    q = OtherIncome.query.filter_by(tenant_id=tid).filter(OtherIncome.deleted_at.is_(None))
    if date_from:
        try:
            q = q.filter(OtherIncome.income_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(OtherIncome.income_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            pass

    income_list = q.order_by(OtherIncome.income_date.desc(), OtherIncome.id.desc()).all()
    total = sum(float(i.amount) for i in income_list)
    currency = get_currency(tid)

    return render_template(
        'accounting/income.html',
        income_list=income_list,
        total=total,
        currency=currency,
        filter_date_from=date_from,
        filter_date_to=date_to,
    )


@accounting_bp.route('/income/add', methods=['GET', 'POST'])
@login_required
def add_income():
    _require_accounting()
    tid = _tid()
    currency = get_currency(tid)

    if request.method == 'POST':
        try:
            amount = Decimal(request.form['amount'].strip())
        except (InvalidOperation, KeyError):
            flash('Invalid amount.', 'danger')
            return redirect(request.url)

        desc = request.form.get('description', '').strip()
        if not desc:
            flash('Description is required.', 'danger')
            return redirect(request.url)

        try:
            inc_date = datetime.strptime(request.form['income_date'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            flash('Invalid date.', 'danger')
            return redirect(request.url)

        income_rec = OtherIncome(
            tenant_id   = tid,
            amount      = amount,
            currency    = currency,
            description = desc,
            income_date = inc_date,
            reference   = request.form.get('reference', '').strip() or None,
            notes       = request.form.get('notes', '').strip() or None,
            created_by  = current_user.id,
        )
        db.session.add(income_rec)
        db.session.commit()
        flash('Income record added.', 'success')
        return redirect(url_for('accounting_bp.income'))

    return render_template(
        'accounting/add_income.html',
        income=None,
        currency=currency,
        today=date.today().isoformat(),
    )


@accounting_bp.route('/income/<int:income_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_income(income_id):
    _require_accounting()
    tid = _tid()
    income_rec = OtherIncome.query.filter_by(id=income_id, tenant_id=tid).first_or_404()
    currency = get_currency(tid)

    if request.method == 'POST':
        try:
            income_rec.amount = Decimal(request.form['amount'].strip())
        except (InvalidOperation, KeyError):
            flash('Invalid amount.', 'danger')
            return redirect(request.url)

        desc = request.form.get('description', '').strip()
        if not desc:
            flash('Description is required.', 'danger')
            return redirect(request.url)

        try:
            income_rec.income_date = datetime.strptime(request.form['income_date'], '%Y-%m-%d').date()
        except (ValueError, KeyError):
            flash('Invalid date.', 'danger')
            return redirect(request.url)

        income_rec.description = desc
        income_rec.reference   = request.form.get('reference', '').strip() or None
        income_rec.notes       = request.form.get('notes', '').strip() or None
        db.session.commit()
        flash('Income record updated.', 'success')
        return redirect(url_for('accounting_bp.income'))

    return render_template(
        'accounting/add_income.html',
        income=income_rec,
        currency=currency,
        today=date.today().isoformat(),
    )


@accounting_bp.route('/income/<int:income_id>/delete', methods=['POST'])
@login_required
def delete_income(income_id):
    _require_accounting()
    tid = _tid()
    income_rec = OtherIncome.query.filter_by(id=income_id, tenant_id=tid).first_or_404()
    income_rec.deleted_at = datetime.utcnow()
    db.session.commit()
    flash('Income record deleted.', 'success')
    return redirect(url_for('accounting_bp.income'))


# ─────────────────────────────────────────────────────────────
# P&L Report
# ─────────────────────────────────────────────────────────────

def _pl_data(tid: int, start: date, end: date) -> dict:
    """Compute P&L components for the given date range."""
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt   = datetime.combine(end,   datetime.max.time())

    # ── Unit sales ──────────────────────────────────────────
    unit_rows = (
        db.session.query(
            func.coalesce(func.sum(SaleItem.price_at_sale), 0).label('pretax'),
            func.coalesce(
                func.sum(SaleItem.price_at_sale * SaleItem.vat_rate / 100), 0
            ).label('vat'),
        )
        .join(SaleTransaction, SaleItem.sale_id == SaleTransaction.id)
        .join(ProductInstance, SaleItem.product_instance_id == ProductInstance.id)
        .join(Product, ProductInstance.product_id == Product.id)
        .filter(
            Product.tenant_id == tid,
            SaleTransaction.date_sold >= start_dt,
            SaleTransaction.date_sold <= end_dt,
        )
        .one()
    )
    unit_sales_pretax = float(unit_rows.pretax or 0)
    unit_sales_vat    = float(unit_rows.vat or 0)
    unit_sales_total  = unit_sales_pretax + unit_sales_vat

    # ── Parts sales ─────────────────────────────────────────
    parts_total = db.session.query(
        func.coalesce(func.sum(PartSaleTransaction.total_amount), 0)
    ).filter(
        PartSaleTransaction.tenant_id == tid,
        PartSaleTransaction.sold_at >= start_dt,
        PartSaleTransaction.sold_at <= end_dt,
    ).scalar() or 0
    parts_total = float(parts_total)

    # ── Other income ────────────────────────────────────────
    other_income_total = db.session.query(
        func.coalesce(func.sum(OtherIncome.amount), 0)
    ).filter(
        OtherIncome.tenant_id == tid,
        OtherIncome.deleted_at.is_(None),
        OtherIncome.income_date >= start,
        OtherIncome.income_date <= end,
    ).scalar() or 0
    other_income_total = float(other_income_total)

    total_income = unit_sales_total + parts_total + other_income_total

    # ── Expenses by category ────────────────────────────────
    exp_rows = (
        db.session.query(
            ExpenseCategory.name.label('cat_name'),
            ExpenseCategory.icon.label('cat_icon'),
            func.coalesce(func.sum(Expense.amount), 0).label('total'),
        )
        .outerjoin(
            Expense,
            (Expense.category_id == ExpenseCategory.id)
            & (Expense.deleted_at.is_(None))
            & (Expense.expense_date >= start)
            & (Expense.expense_date <= end)
        )
        .filter(ExpenseCategory.tenant_id == tid)
        .group_by(ExpenseCategory.id, ExpenseCategory.name, ExpenseCategory.icon)
        .order_by(func.sum(Expense.amount).desc().nullslast())
        .all()
    )
    # Also uncategorised
    uncat_total = db.session.query(
        func.coalesce(func.sum(Expense.amount), 0)
    ).filter(
        Expense.tenant_id == tid,
        Expense.category_id.is_(None),
        Expense.deleted_at.is_(None),
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    ).scalar() or 0
    uncat_total = float(uncat_total)

    expense_lines = [
        {'name': row.cat_name, 'icon': row.cat_icon, 'amount': float(row.total)}
        for row in exp_rows if float(row.total) > 0
    ]
    if uncat_total > 0:
        expense_lines.append({'name': 'Uncategorised', 'icon': 'bi-question-circle', 'amount': uncat_total})

    total_expenses = sum(l['amount'] for l in expense_lines)
    net_profit     = total_income - total_expenses
    profit_margin  = (net_profit / total_income * 100) if total_income else 0

    return {
        'unit_sales_pretax': unit_sales_pretax,
        'unit_sales_vat':    unit_sales_vat,
        'unit_sales_total':  unit_sales_total,
        'parts_total':       parts_total,
        'other_income':      other_income_total,
        'total_income':      total_income,
        'expense_lines':     expense_lines,
        'total_expenses':    total_expenses,
        'net_profit':        net_profit,
        'profit_margin':     profit_margin,
    }


@accounting_bp.route('/pl')
@login_required
def pl():
    _require_accounting()
    tid = _tid()
    seed_expense_categories(tid)
    currency = get_currency(tid)

    today = date.today()
    default_from = today.replace(day=1).isoformat()
    default_to   = today.isoformat()
    date_from_str = request.args.get('date_from', default_from)
    date_to_str   = request.args.get('date_to',   default_to)

    try:
        date_from = date.fromisoformat(date_from_str)
    except ValueError:
        date_from = today.replace(day=1)
    try:
        date_to = date.fromisoformat(date_to_str)
    except ValueError:
        date_to = today

    data = _pl_data(tid, date_from, date_to)

    if request.args.get('export') == 'csv':
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['P&L Report', f"{date_from} to {date_to}"])
        w.writerow([])
        w.writerow(['INCOME', ''])
        w.writerow(['Unit Sales (pretax)', f"{data['unit_sales_pretax']:.2f}"])
        w.writerow(['VAT Collected',       f"{data['unit_sales_vat']:.2f}"])
        w.writerow(['Parts Sales',         f"{data['parts_total']:.2f}"])
        w.writerow(['Other Income',        f"{data['other_income']:.2f}"])
        w.writerow(['TOTAL INCOME',        f"{data['total_income']:.2f}"])
        w.writerow([])
        w.writerow(['EXPENSES', ''])
        for line in data['expense_lines']:
            w.writerow([line['name'], f"{line['amount']:.2f}"])
        w.writerow(['TOTAL EXPENSES', f"{data['total_expenses']:.2f}"])
        w.writerow([])
        w.writerow(['NET PROFIT', f"{data['net_profit']:.2f}"])
        w.writerow(['PROFIT MARGIN', f"{data['profit_margin']:.1f}%"])
        output = buf.getvalue()
        return Response(
            output,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment;filename=pl_{date_from}_{date_to}.csv'},
        )

    return render_template('accounting/pl.html',
        currency=currency,
        date_from=date_from_str,
        date_to=date_to_str,
        **data,
    )


# ─────────────────────────────────────────────────────────────
# Cash Flow (12-month monthly breakdown)
# ─────────────────────────────────────────────────────────────

@accounting_bp.route('/cashflow')
@login_required
def cashflow():
    _require_accounting()
    tid = _tid()
    currency = get_currency(tid)

    # Build last 12 complete months + current month
    today = date.today()
    months = []
    for i in range(11, -1, -1):
        # Step back i months from current month
        year  = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year  -= 1
        months.append((year, month))

    def _month_bounds(y, m):
        import calendar
        last_day = calendar.monthrange(y, m)[1]
        return date(y, m, 1), date(y, m, last_day)

    rows = []
    running_balance = 0.0
    for y, m in months:
        start, end = _month_bounds(y, m)
        data = _pl_data(tid, start, end)
        running_balance += data['net_profit']
        rows.append({
            'label':   f"{month_abbr[m]} {y}",
            'income':  data['total_income'],
            'expenses': data['total_expenses'],
            'net':     data['net_profit'],
            'running': running_balance,
        })

    if request.args.get('export') == 'csv':
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Month', 'Income', 'Expenses', 'Net', 'Running Balance'])
        for r in rows:
            w.writerow([r['label'], f"{r['income']:.2f}",
                        f"{r['expenses']:.2f}", f"{r['net']:.2f}", f"{r['running']:.2f}"])
        return Response(
            buf.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=cashflow.csv'},
        )

    chart_labels  = [r['label']    for r in rows]
    chart_income  = [r['income']   for r in rows]
    chart_expense = [r['expenses'] for r in rows]
    chart_net     = [r['net']      for r in rows]

    return render_template('accounting/cashflow.html',
        rows=rows,
        currency=currency,
        chart_labels=chart_labels,
        chart_income=chart_income,
        chart_expense=chart_expense,
        chart_net=chart_net,
    )


# ─────────────────────────────────────────────────────────────
# AR Aging Report
# ─────────────────────────────────────────────────────────────

@accounting_bp.route('/ar_aging')
@login_required
def ar_aging():
    _require_accounting()
    tid = _tid()
    currency = get_currency(tid)
    today = date.today()

    open_ar = AccountReceivable.query.filter(
        AccountReceivable.tenant_id == tid,
        AccountReceivable.status.in_(('open', 'partial', 'overdue')),
    ).all()

    buckets = {
        'current':  {'label': 'Current',      'color': 'success', 'items': [], 'total': 0.0},
        '1_30':     {'label': '1–30 days',     'color': 'warning', 'items': [], 'total': 0.0},
        '31_60':    {'label': '31–60 days',    'color': 'orange',  'items': [], 'total': 0.0},
        '61_90':    {'label': '61–90 days',    'color': 'danger',  'items': [], 'total': 0.0},
        '90plus':   {'label': '90+ days',      'color': 'dark',    'items': [], 'total': 0.0},
    }

    for ar in open_ar:
        bal = ar.balance
        if ar.due_date is None or ar.due_date >= today:
            key = 'current'
        else:
            days = (today - ar.due_date).days
            if   days <= 30:  key = '1_30'
            elif days <= 60:  key = '31_60'
            elif days <= 90:  key = '61_90'
            else:             key = '90plus'
        buckets[key]['items'].append(ar)
        buckets[key]['total'] += bal

    grand_total = sum(b['total'] for b in buckets.values())

    if request.args.get('export') == 'csv':
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['AR Aging Report', today.isoformat()])
        w.writerow([])
        for key, b in buckets.items():
            w.writerow([b['label']])
            w.writerow(['Customer', 'Invoice', 'Due Date', 'Balance'])
            for ar in b['items']:
                inv_num = ar.invoice.invoice_number if ar.invoice else '—'
                due = ar.due_date.isoformat() if ar.due_date else '—'
                w.writerow([ar.customer.name, inv_num, due, f"{ar.balance:.2f}"])
            w.writerow(['Subtotal', '', '', f"{b['total']:.2f}"])
            w.writerow([])
        w.writerow(['GRAND TOTAL', '', '', f"{grand_total:.2f}"])
        return Response(
            buf.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment;filename=ar_aging_{today}.csv'},
        )

    return render_template('accounting/ar_aging.html',
        buckets=buckets,
        grand_total=grand_total,
        currency=currency,
        today=today,
    )


# ─────────────────────────────────────────────────────────────
# Expense Categories Management (admin only)
# ─────────────────────────────────────────────────────────────

@accounting_bp.route('/categories', methods=['GET', 'POST'])
@login_required
def categories():
    if current_user.role != 'admin':
        abort(403)
    tid = _tid()
    seed_expense_categories(tid)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            name = request.form.get('name', '').strip()
            icon = request.form.get('icon', 'bi-receipt').strip() or 'bi-receipt'
            slug = name.lower().replace(' ', '-').replace('&', 'and')
            if not name:
                flash('Category name is required.', 'danger')
            else:
                existing = ExpenseCategory.query.filter_by(slug=slug, tenant_id=tid).first()
                if existing:
                    flash('A category with that name already exists.', 'warning')
                else:
                    db.session.add(ExpenseCategory(name=name, slug=slug, icon=icon, tenant_id=tid))
                    db.session.commit()
                    flash('Category added.', 'success')

        elif action == 'edit':
            cat_id = request.form.get('cat_id', type=int)
            cat = ExpenseCategory.query.filter_by(id=cat_id, tenant_id=tid).first_or_404()
            name = request.form.get('name', '').strip()
            if not name:
                flash('Name is required.', 'danger')
            else:
                cat.name = name
                cat.icon = request.form.get('icon', cat.icon).strip() or cat.icon
                db.session.commit()
                flash('Category updated.', 'success')

        elif action == 'delete':
            cat_id = request.form.get('cat_id', type=int)
            cat = ExpenseCategory.query.filter_by(id=cat_id, tenant_id=tid).first_or_404()
            exp_count = Expense.query.filter_by(category_id=cat_id, tenant_id=tid)\
                               .filter(Expense.deleted_at.is_(None)).count()
            if exp_count > 0:
                flash(f'Cannot delete — {exp_count} expense(s) use this category.', 'danger')
            else:
                db.session.delete(cat)
                db.session.commit()
                flash('Category deleted.', 'success')

        return redirect(url_for('accounting_bp.categories'))

    # Build list with totals
    cats = (
        db.session.query(
            ExpenseCategory,
            func.count(Expense.id).label('exp_count'),
            func.coalesce(func.sum(Expense.amount), 0).label('exp_total'),
        )
        .outerjoin(Expense, (Expense.category_id == ExpenseCategory.id) & (Expense.deleted_at.is_(None)))
        .filter(ExpenseCategory.tenant_id == tid)
        .group_by(ExpenseCategory.id)
        .order_by(ExpenseCategory.name)
        .all()
    )

    # Common Bootstrap-icon options for the picker
    icon_options = [
        'bi-receipt', 'bi-person-badge', 'bi-building', 'bi-truck',
        'bi-tools', 'bi-wrench', 'bi-megaphone', 'bi-box-arrow-in-down',
        'bi-three-dots', 'bi-laptop', 'bi-phone', 'bi-wifi',
        'bi-shield-check', 'bi-bank', 'bi-car-front', 'bi-house',
        'bi-lightbulb', 'bi-printer', 'bi-shop', 'bi-tag',
    ]

    return render_template('accounting/categories.html',
        cats=cats,
        icon_options=icon_options,
    )
