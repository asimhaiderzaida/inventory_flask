"""Customer purchase-order management blueprint."""
import csv
import io
import logging
from datetime import datetime, timezone, date as date_type

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, jsonify, Response,
)
from flask_login import login_required, current_user

from inventory_flask_app import db
from inventory_flask_app.models import CustomerOrder, Customer
from inventory_flask_app.utils import get_now_for_tenant

logger = logging.getLogger(__name__)

orders_bp = Blueprint('orders_bp', __name__, url_prefix='/purchase-orders')


# ── helpers ──────────────────────────────────────────────────────────────────

def _require_admin():
    if current_user.role != 'admin':
        abort(403)


# ── list ─────────────────────────────────────────────────────────────────────

@orders_bp.route('/')
@login_required
def index():
    tid  = current_user.tenant_id
    tab  = request.args.get('tab', 'open')
    q    = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = CustomerOrder.query.filter_by(tenant_id=tid)
    if tab != 'all':
        query = query.filter_by(status=tab)
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(
                CustomerOrder.customer_name.ilike(like),
                CustomerOrder.model_description.ilike(like),
            )
        )
    orders = query.order_by(CustomerOrder.created_at.desc()).paginate(page=page, per_page=30)

    counts = {
        'open':   CustomerOrder.query.filter_by(tenant_id=tid, status='open').count(),
        'closed': CustomerOrder.query.filter_by(tenant_id=tid, status='closed').count(),
        'all':    CustomerOrder.query.filter_by(tenant_id=tid).count(),
    }
    return render_template('orders/index.html', orders=orders, tab=tab, q=q, counts=counts)


# ── CSV export ────────────────────────────────────────────────────────────────

@orders_bp.route('/export')
@login_required
def export_csv():
    tid = current_user.tenant_id
    rows = CustomerOrder.query.filter_by(tenant_id=tid).order_by(CustomerOrder.created_at.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['ID', 'Customer', 'Model', 'Qty', 'Price/unit', 'Total Budget',
                     'Delivery', 'Deposit', 'Payment Status', 'Status', 'Created', 'Notes'])
    for o in rows:
        writer.writerow([
            o.id, o.customer_name, o.model_description, o.quantity,
            o.expected_price, o.total_budget,
            o.delivery_date.isoformat() if o.delivery_date else '',
            o.deposit_amount, o.payment_status, o.status,
            o.created_at.strftime('%Y-%m-%d'),
            (o.notes or '').replace('\n', ' '),
        ])
    output = buf.getvalue()
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=orders.csv'},
    )


# ── create ────────────────────────────────────────────────────────────────────

@orders_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_order():
    tid = current_user.tenant_id
    if request.method == 'POST':
        try:
            customer_id   = request.form.get('customer_id') or None
            customer_name = request.form.get('customer_name', '').strip()
            if not customer_name:
                flash('Customer name is required.', 'danger')
                return redirect(url_for('orders_bp.new_order'))

            qty   = max(1, int(request.form.get('quantity') or 1))
            price = request.form.get('expected_price') or None
            if price:
                price = float(price)

            total = (qty * price) if (price is not None) else None

            dep_raw = request.form.get('deposit_amount') or None
            deposit = float(dep_raw) if dep_raw else None

            del_raw = request.form.get('delivery_date') or None
            delivery = (datetime.strptime(del_raw, '%Y-%m-%d').date()
                        if del_raw else None)

            order = CustomerOrder(
                tenant_id         = tid,
                customer_id       = int(customer_id) if customer_id else None,
                customer_name     = customer_name,
                model_description = request.form.get('model_description', '').strip(),
                quantity          = qty,
                expected_price    = price,
                total_budget      = total,
                delivery_date     = delivery,
                deposit_amount    = deposit,
                deposit_paid      = bool(request.form.get('deposit_paid')),
                payment_status    = request.form.get('payment_status', 'none'),
                notes             = request.form.get('notes', '').strip() or None,
                created_by        = current_user.id,
                created_at        = get_now_for_tenant(),
                status            = 'open',
            )
            db.session.add(order)
            db.session.commit()
            flash('Order created.', 'success')
            return redirect(url_for('orders_bp.detail', order_id=order.id))
        except Exception as e:
            db.session.rollback()
            logger.error(f'new_order error: {e}', exc_info=True)
            flash(f'Error creating order: {e}', 'danger')

    customers = Customer.query.filter_by(tenant_id=tid).order_by(Customer.name).all()
    return render_template('orders/new_order.html', customers=customers)


# ── customer search AJAX ──────────────────────────────────────────────────────

@orders_bp.route('/customer_search')
@login_required
def customer_search():
    tid = current_user.tenant_id
    q   = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    like = f'%{q}%'
    results = (
        Customer.query
        .filter_by(tenant_id=tid)
        .filter(db.or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
        .limit(10).all()
    )
    return jsonify([
        {'id': c.id, 'name': c.name, 'phone': c.phone or '', 'email': c.email or ''}
        for c in results
    ])


# ── detail ────────────────────────────────────────────────────────────────────

@orders_bp.route('/<int:order_id>')
@login_required
def detail(order_id):
    tid   = current_user.tenant_id
    order = CustomerOrder.query.filter_by(id=order_id, tenant_id=tid).first_or_404()
    return render_template('orders/detail.html', order=order)


# ── close ─────────────────────────────────────────────────────────────────────

@orders_bp.route('/<int:order_id>/close', methods=['POST'])
@login_required
def close_order(order_id):
    tid   = current_user.tenant_id
    order = CustomerOrder.query.filter_by(id=order_id, tenant_id=tid).first_or_404()
    if order.status == 'open':
        order.status    = 'closed'
        order.closed_at = get_now_for_tenant()
        db.session.commit()
        flash('Order closed.', 'success')
    return redirect(url_for('orders_bp.detail', order_id=order_id))


# ── reopen ────────────────────────────────────────────────────────────────────

@orders_bp.route('/<int:order_id>/reopen', methods=['POST'])
@login_required
def reopen_order(order_id):
    tid   = current_user.tenant_id
    order = CustomerOrder.query.filter_by(id=order_id, tenant_id=tid).first_or_404()
    if order.status == 'closed':
        order.status    = 'open'
        order.closed_at = None
        db.session.commit()
        flash('Order reopened.', 'success')
    return redirect(url_for('orders_bp.detail', order_id=order_id))


# ── delete ────────────────────────────────────────────────────────────────────

@orders_bp.route('/<int:order_id>/delete', methods=['POST'])
@login_required
def delete_order(order_id):
    _require_admin()
    tid   = current_user.tenant_id
    order = CustomerOrder.query.filter_by(id=order_id, tenant_id=tid).first_or_404()
    db.session.delete(order)
    db.session.commit()
    flash('Order deleted.', 'info')
    return redirect(url_for('orders_bp.index'))
