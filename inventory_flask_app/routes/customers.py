import logging
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import or_
from ..models import db, Customer
from inventory_flask_app.utils.utils import admin_or_supervisor_required, module_required

logger = logging.getLogger(__name__)
customers_bp = Blueprint('customers_bp', __name__)

@customers_bp.route('/customers/add', methods=['GET', 'POST'])
@login_required
@module_required('customers', 'full')
def add_customer():
    from inventory_flask_app.models import TenantSettings
    settings = {}
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}

    next_page = request.args.get('next', '')
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()

        # Check duplicates: same name OR same non-empty email OR same non-empty phone
        dup_filters = [Customer.name == name]
        if email:
            dup_filters.append(Customer.email == email)
        if phone:
            dup_filters.append(Customer.phone == phone)
        existing = Customer.query.filter(
            Customer.tenant_id == current_user.tenant_id,
            or_(*dup_filters)
        ).first()
        if existing:
            flash(
                f'A customer with that name, phone, or email already exists: '
                f'<a href="{url_for("customers_bp.customer_profile", customer_id=existing.id, view="orders")}">'
                f'{existing.name}</a>',
                'warning'
            )
            return render_template('add_customer.html', settings=settings)

        company = request.form.get('company', '').strip()
        address = request.form.get('address', '').strip()
        city = request.form.get('city', '').strip()
        country = request.form.get('country', '').strip()
        cust_notes = request.form.get('notes', '').strip()

        new_customer = Customer(
            name=name, phone=phone, email=email,
            company=company or None,
            address=address or None,
            city=city or None,
            country=country or None,
            notes=cust_notes or None,
            tenant_id=current_user.tenant_id,
        )
        db.session.add(new_customer)
        db.session.commit()

        flash('✅ Customer added successfully!', 'success')
        return redirect(url_for(
            'customers_bp.customer_center' if next_page == 'customer_center' else 'sales_bp.create_sale_form'
        ))

    return render_template('add_customer.html', settings=settings)


@customers_bp.route('/customers/api/search')
@login_required
@module_required('customers', 'view')
def api_customer_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    results = (
        Customer.query
        .filter(
            Customer.tenant_id == current_user.tenant_id,
            or_(
                Customer.name.ilike(f'%{q}%'),
                Customer.phone.ilike(f'%{q}%'),
            )
        )
        .order_by(Customer.name)
        .limit(10)
        .all()
    )
    return jsonify([
        {
            'id':      c.id,
            'name':    c.name,
            'phone':   c.phone or '',
            'email':   c.email or '',
            'company': c.company or '',
        }
        for c in results
    ])


# Customer center route with search, sort, and filter functionality
@customers_bp.route('/customers/center')
@login_required
@module_required('customers', 'view')
def customer_center():
    from inventory_flask_app.models import TenantSettings, SaleTransaction, AccountReceivable
    from sqlalchemy import func, case

    search    = request.args.get('search', '').strip()
    sort_by   = request.args.get('sort', 'name')       # name|total_spent|last_purchase|balance
    filt      = request.args.get('filter', 'all')       # all|has_balance|no_purchases|recent
    page      = request.args.get('page', 1, type=int)
    per_page  = 25

    query = Customer.query.filter_by(tenant_id=current_user.tenant_id)

    # ── Text search ──────────────────────────────────────────
    if search:
        query = query.filter(
            or_(
                Customer.name.ilike(f'%{search}%'),
                Customer.phone.ilike(f'%{search}%'),
                Customer.email.ilike(f'%{search}%'),
                Customer.company.ilike(f'%{search}%'),
            )
        )

    # ── SQL-level filters (H18: must filter before paginate) ─
    thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    if filt == 'has_balance':
        open_cust_ids = db.session.query(AccountReceivable.customer_id).filter(
            AccountReceivable.tenant_id == current_user.tenant_id,
            AccountReceivable.status.in_(('open', 'partial', 'overdue')),
            AccountReceivable.amount_due > AccountReceivable.amount_paid,
        ).distinct()
        query = query.filter(Customer.id.in_(open_cust_ids))
    elif filt == 'no_purchases':
        has_sales_ids = db.session.query(SaleTransaction.customer_id).filter(
            SaleTransaction.customer_id.isnot(None)
        ).distinct()
        query = query.filter(~Customer.id.in_(has_sales_ids))
    elif filt == 'recent':
        recent_cust_ids = db.session.query(SaleTransaction.customer_id).filter(
            SaleTransaction.customer_id.isnot(None),
            SaleTransaction.date_sold >= thirty_days_ago,
        ).distinct()
        query = query.filter(Customer.id.in_(recent_cust_ids))

    # ── Fetch the page of customers ──────────────────────────
    if sort_by == 'name':
        query = query.order_by(Customer.name)
    else:
        query = query.order_by(Customer.name)  # fallback; will re-sort in Python after annotation

    paginated  = query.paginate(page=page, per_page=per_page)
    customers  = paginated.items
    cust_ids   = [c.id for c in customers]

    # ── Single-pass aggregation queries ──────────────────────
    sale_stats = {}   # customer_id → {total_orders, total_spent, last_purchase}
    ar_totals  = {}   # customer_id → open_balance

    if cust_ids:
        # Sale stats
        rows = (
            db.session.query(
                SaleTransaction.customer_id,
                func.count(func.distinct(SaleTransaction.order_id)).label('total_orders'),
                func.sum(SaleTransaction.price_at_sale).label('total_spent'),
                func.max(SaleTransaction.date_sold).label('last_purchase'),
            )
            .filter(SaleTransaction.customer_id.in_(cust_ids))
            .group_by(SaleTransaction.customer_id)
            .all()
        )
        for r in rows:
            sale_stats[r.customer_id] = {
                'total_orders': r.total_orders or 0,
                'total_spent':  float(r.total_spent or 0),
                'last_purchase': r.last_purchase,
            }

        # AR open balances
        ar_rows = (
            db.session.query(
                AccountReceivable.customer_id,
                func.sum(AccountReceivable.amount_due - AccountReceivable.amount_paid).label('balance'),
            )
            .filter(
                AccountReceivable.customer_id.in_(cust_ids),
                AccountReceivable.tenant_id == current_user.tenant_id,
                AccountReceivable.status.in_(('open', 'partial', 'overdue')),
            )
            .group_by(AccountReceivable.customer_id)
            .all()
        )
        ar_totals = {r.customer_id: float(r.balance or 0) for r in ar_rows}

    # Annotate customers
    for c in customers:
        s = sale_stats.get(c.id, {})
        c._total_orders  = s.get('total_orders', 0)
        c._total_spent   = s.get('total_spent', 0.0)
        c._last_purchase = s.get('last_purchase')
        c._open_balance  = ar_totals.get(c.id, 0.0)

    # ── Client-side sort (post-annotation) ───────────────────
    if sort_by == 'total_spent':
        customers.sort(key=lambda c: c._total_spent, reverse=True)
    elif sort_by == 'last_purchase':
        customers.sort(key=lambda c: c._last_purchase or datetime.min, reverse=True)
    elif sort_by == 'balance':
        customers.sort(key=lambda c: c._open_balance, reverse=True)

    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}

    return render_template(
        'customer_center.html',
        customers=customers,
        search=search,
        sort_by=sort_by,
        active_filter=filt,
        settings=settings,
        pagination=paginated,
    )

@customers_bp.route('/customers/<int:customer_id>/profile')
@login_required
@module_required('customers', 'view')
def customer_profile(customer_id):
    from inventory_flask_app.models import (
        SaleTransaction, ProductInstance, Product, Invoice,
        AccountReceivable, CustomerOrderTracking, CustomerNote, CustomerCommunication,
        Order, Return, CreditNote,
    )
    from sqlalchemy.orm import joinedload
    from sqlalchemy import func

    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()
    view = request.args.get('view', 'orders')

    # ── Search terms (persisted for form re-population) ──────
    order_search = request.args.get('order_search', '').strip()
    sales_search = request.args.get('sales_search', '').strip()

    order_details_map = {}
    orders_list = []
    sales_data = []

    # ── Lifetime stats (always computed) ─────────────────────
    all_sales = (SaleTransaction.query
                 .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
                 .join(Product, ProductInstance.product_id == Product.id)
                 .filter(
                     SaleTransaction.customer_id == customer.id,
                     Product.tenant_id == current_user.tenant_id,
                 )
                 .order_by(SaleTransaction.date_sold.asc())
                 .all())
    total_units_sold = len(all_sales)
    total_spent = sum(float(s.price_at_sale or 0) for s in all_sales)
    first_purchase = all_sales[0].date_sold if all_sales else None
    last_purchase  = all_sales[-1].date_sold if all_sales else None

    # Order count via distinct order_ids
    order_ids = list({s.order_id for s in all_sales if s.order_id})
    total_orders = len(order_ids)
    avg_order_value = (total_spent / total_orders) if total_orders else 0

    # ── Units / Sales History view ───────────────────────────
    if view == 'units':
        q = (SaleTransaction.query
             .options(
                 joinedload(SaleTransaction.product_instance)
                 .joinedload(ProductInstance.product)
             )
             .join(ProductInstance, SaleTransaction.product_instance_id == ProductInstance.id)
             .join(Product, ProductInstance.product_id == Product.id)
             .filter(
                 SaleTransaction.customer_id == customer.id,
                 Product.tenant_id == current_user.tenant_id,
             ))
        if sales_search:
            q = q.filter(
                or_(
                    ProductInstance.serial.ilike(f'%{sales_search}%'),
                    ProductInstance.asset.ilike(f'%{sales_search}%'),
                    Product.model.ilike(f'%{sales_search}%'),
                    Product.item_name.ilike(f'%{sales_search}%'),
                )
            )
        for sale in q.order_by(SaleTransaction.date_sold.desc()).all():
            instance = sale.product_instance
            product  = instance.product if instance else None
            sales_data.append({
                "serial":        instance.serial       if instance else "",
                "asset":         instance.asset        if instance else "",
                "model":         product.model         if product  else "",
                "item_name":     product.item_name     if product  else "",
                "grade":         product.grade         if product  else "",
                "ram":           product.ram           if product  else "",
                "cpu":           product.cpu           if product  else "",
                "disk1size":     product.disk1size     if product  else "",
                "display":       product.display       if product  else "",
                "gpu1":          product.gpu1          if product  else "",
                "gpu2":          product.gpu2          if product  else "",
                "status":        instance.status       if instance else "",
                "price_at_sale": sale.price_at_sale,
                "date_sold":     sale.date_sold,
                "notes":         sale.notes,
            })

    # ── Orders view ──────────────────────────────────────────
    elif view == 'orders':
        orders_q = Order.query.filter_by(customer_id=customer.id).order_by(Order.created_at.desc())
        for order in orders_q.all():
            transactions = (SaleTransaction.query
                            .options(
                                joinedload(SaleTransaction.product_instance)
                                .joinedload(ProductInstance.product),
                                joinedload(SaleTransaction.invoice)
                            )
                            .filter_by(order_id=order.id)
                            .all())
            units_list = []
            invoice = None
            for sale in transactions:
                instance = sale.product_instance
                product  = instance.product if instance else None
                if sale.invoice_id and not invoice:
                    invoice = sale.invoice
                row = {
                    "serial":        instance.serial       if instance else "",
                    "asset":         instance.asset        if instance else "",
                    "model":         product.model         if product  else "",
                    "item_name":     product.item_name     if product  else "",
                    "grade":         product.grade         if product  else "",
                    "ram":           product.ram           if product  else "",
                    "cpu":           product.cpu           if product  else "",
                    "disk1size":     product.disk1size     if product  else "",
                    "display":       product.display       if product  else "",
                    "gpu1":          product.gpu1          if product  else "",
                    "gpu2":          product.gpu2          if product  else "",
                    "status":        instance.status       if instance else "",
                    "price_at_sale": sale.price_at_sale,
                    "date_sold":     sale.date_sold,
                    "notes":         sale.notes,
                }
                units_list.append(row)

            # Apply search filter
            if order_search:
                term = order_search.lower()
                units_list = [
                    u for u in units_list
                    if term in (u['serial'] or '').lower()
                    or term in (u['model'] or '').lower()
                    or term in (u['item_name'] or '').lower()
                    or term in (invoice.invoice_number or '' if invoice else '').lower()
                ]
                if not units_list:
                    continue

            orders_list.append({
                "order_number":  order.order_number,
                "order_date":    order.created_at,
                "invoice_id":    invoice.id             if invoice else None,
                "invoice_number": invoice.invoice_number if invoice else "—",
                "total_units":   len(units_list),
                "total_amount":  sum(u["price_at_sale"] or 0 for u in units_list),
            })
            order_details_map[order.order_number] = units_list

    # ── Reservations view ─────────────────────────────────────
    reservations = []
    if view == 'reservations':
        reservations = (
            CustomerOrderTracking.query
            .options(
                joinedload(CustomerOrderTracking.product_instance)
                .joinedload(ProductInstance.product)
            )
            .filter_by(customer_id=customer.id)
            .order_by(CustomerOrderTracking.reserved_date.desc())
            .all()
        )

    # ── Notes view ───────────────────────────────────────────
    notes_list = []
    if view == 'notes':
        notes_list = (CustomerNote.query
                      .filter_by(customer_id=customer.id)
                      .order_by(CustomerNote.created_at.desc())
                      .all())

    # ── Communications view ──────────────────────────────────
    comms_list = []
    if view == 'comms':
        comms_list = (CustomerCommunication.query
                      .filter_by(customer_id=customer.id)
                      .order_by(CustomerCommunication.sent_at.desc())
                      .all())

    # ── Returns view ─────────────────────────────────────────
    customer_returns = []
    if view == 'returns':
        from sqlalchemy.orm import joinedload as _jl
        # Get customer's invoice IDs and sold instance IDs
        cust_invoice_ids = [
            inv.id for inv in
            Invoice.query.filter_by(customer_id=customer.id, tenant_id=current_user.tenant_id).all()
        ]
        cust_instance_ids = [
            s.product_instance_id for s in
            SaleTransaction.query.filter_by(customer_id=customer.id).all()
        ]
        from sqlalchemy import or_ as _or
        if cust_invoice_ids or cust_instance_ids:
            customer_returns = (
                Return.query
                .filter(
                    Return.tenant_id == current_user.tenant_id,
                    _or(
                        Return.invoice_id.in_(cust_invoice_ids) if cust_invoice_ids else db.false(),
                        Return.instance_id.in_(cust_instance_ids) if cust_instance_ids else db.false(),
                    )
                )
                .options(
                    _jl(Return.instance),
                    _jl(Return.invoice),
                )
                .order_by(Return.return_date.desc())
                .all()
            )

    # ── Credit note balance (always computed) ─────────────────
    unapplied_cns = CreditNote.query.filter_by(
        customer_id=customer.id,
        tenant_id=current_user.tenant_id,
        status='unapplied',
    ).all()
    credit_note_balance = sum(float(cn.amount or 0) for cn in unapplied_cns)

    # ── AR (always loaded — shown in sidebar card) ────────────
    open_ar = AccountReceivable.query.filter(
        AccountReceivable.customer_id == customer.id,
        AccountReceivable.tenant_id == current_user.tenant_id,
        AccountReceivable.status.in_(('open', 'partial', 'overdue')),
    ).order_by(AccountReceivable.due_date.asc().nullslast()).all()
    total_ar_balance = sum(ar.balance for ar in open_ar)

    stats = {
        "total_orders":     total_orders,
        "total_units":      total_units_sold,
        "total_spent":      total_spent,
        "avg_order_value":  avg_order_value,
        "first_purchase":   first_purchase,
        "last_purchase":    last_purchase,
        "outstanding":          total_ar_balance,
        "credit_note_balance":  credit_note_balance,
    }

    return render_template(
        "customer_profile.html",
        customer=customer,
        sales_data=sales_data,
        orders_list=orders_list,
        order_details_map=order_details_map,
        reservations=reservations,
        notes_list=notes_list,
        comms_list=comms_list,
        customer_returns=customer_returns,
        credit_note_balance=credit_note_balance,
        unapplied_cns=unapplied_cns,
        view=view,
        open_ar=open_ar,
        total_ar_balance=total_ar_balance,
        stats=stats,
        order_search=order_search,
        sales_search=sales_search,
    )


@customers_bp.route('/customers/<int:customer_id>/notes/add', methods=['POST'])
@login_required
@module_required('customers', 'full')
def add_customer_note(customer_id):
    from inventory_flask_app.models import CustomerNote
    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()
    note_text = request.form.get('note', '').strip()
    if note_text:
        note = CustomerNote(
            tenant_id=current_user.tenant_id,
            customer_id=customer.id,
            note=note_text,
            created_by=current_user.id,
        )
        db.session.add(note)
        db.session.commit()
        flash('Note added.', 'success')
    return redirect(url_for('customers_bp.customer_profile', customer_id=customer.id, view='notes'))


@customers_bp.route('/customers/<int:customer_id>/notes/<int:note_id>/delete', methods=['POST'])
@login_required
@module_required('customers', 'full')
def delete_customer_note(customer_id, note_id):
    from inventory_flask_app.models import CustomerNote
    # Only admin can delete notes
    if current_user.role not in ('admin', 'supervisor'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('customers_bp.customer_profile', customer_id=customer_id, view='notes'))
    note = CustomerNote.query.filter_by(id=note_id, customer_id=customer_id, tenant_id=current_user.tenant_id).first_or_404()
    db.session.delete(note)
    db.session.commit()
    flash('Note deleted.', 'success')
    return redirect(url_for('customers_bp.customer_profile', customer_id=customer_id, view='notes'))

@customers_bp.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
@module_required('customers', 'full')
def edit_customer(customer_id):
    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()
    if request.method == 'POST':
        customer.name    = request.form.get('name', '').strip()
        customer.phone   = request.form.get('phone', '').strip() or None
        customer.email   = request.form.get('email', '').strip() or None
        customer.company = request.form.get('company', '').strip() or None
        customer.address = request.form.get('address', '').strip() or None
        customer.city    = request.form.get('city', '').strip() or None
        customer.country = request.form.get('country', '').strip() or None
        customer.notes   = request.form.get('notes', '').strip() or None
        db.session.commit()
        flash('Customer updated successfully!', 'success')
        return redirect(url_for('customers_bp.customer_profile', customer_id=customer.id, view='orders'))
    return render_template('edit_customer.html', customer=customer)


@customers_bp.route('/customers/<int:customer_id>/delete', methods=['POST'])
@login_required
@admin_or_supervisor_required
def delete_customer(customer_id):
    from inventory_flask_app.models import SaleTransaction, AccountReceivable, CustomerOrderTracking
    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()

    has_sales = SaleTransaction.query.filter_by(customer_id=customer.id).first()
    has_ar    = AccountReceivable.query.filter_by(customer_id=customer.id).first()
    has_res   = CustomerOrderTracking.query.filter_by(customer_id=customer.id).first()

    if has_sales or has_ar or has_res:
        flash('Cannot delete a customer with purchase history, outstanding balance, or reservations.', 'danger')
        return redirect(url_for('customers_bp.edit_customer', customer_id=customer.id))

    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted.', 'success')
    return redirect(url_for('customers_bp.customer_center'))

from openpyxl import Workbook
from flask import send_file
from io import BytesIO
from inventory_flask_app.utils import get_now_for_tenant

@customers_bp.route('/customers/<int:customer_id>/export_sales')
@login_required
@module_required('customers', 'view')
def export_customer_sales(customer_id):
    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first_or_404()
    from inventory_flask_app.models import SaleTransaction, TenantSettings
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}

    sales = SaleTransaction.query.filter_by(customer_id=customer.id).order_by(SaleTransaction.date_sold.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales History"
    ws.append([
        'Date Sold',
        settings.get("label_serial_number", "Serial"),
        settings.get("label_asset", "Asset"),
        settings.get("label_item_name", "Item Name"),
        settings.get("label_model", "Model"),
        settings.get("label_cpu", "CPU"),
        settings.get("label_ram", "RAM"),
        settings.get("label_disk1size", "Disk"),
        settings.get("label_display", "Display"),
        settings.get("label_gpu1", "GPU1"),
        settings.get("label_gpu2", "GPU2"),
        settings.get("label_grade", "Grade"),
        settings.get("label_status", "Status"),
        settings.get("label_price", "Price"),
        settings.get("label_notes", "Notes")
    ])
    for sale in sales:
        instance = sale.product_instance
        product = instance.product if instance else None
        ws.append([
            sale.date_sold.strftime('%Y-%m-%d') if sale.date_sold else get_now_for_tenant().strftime('%Y-%m-%d'),
            instance.serial if instance else '',
            instance.asset if instance else '',
            product.item_name if product else '',
            product.model if product else '',
            product.cpu if product else '',
            product.ram if product else '',
            product.disk1size if product else '',
            product.display if product else '',
            product.gpu1 if product else '',
            product.gpu2 if product else '',
            product.grade if product else '',
            instance.status if instance else '',
            sale.price_at_sale,
            sale.notes or ''
        ])
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"customer_{customer.id}_sales.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ─────────────────────────────────────────────────────────────
# Customer Portal — public (no login required)
# ─────────────────────────────────────────────────────────────
@customers_bp.route('/portal/<token>')
def customer_portal(token):
    from inventory_flask_app.models import (
        Order, SaleTransaction, CustomerOrderTracking,
        TenantSettings, ProductInstance, Product
    )

    customer = Customer.query.filter_by(portal_token=token).first_or_404()

    # Check token expiry (30-day TTL)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if customer.portal_token_expires_at and customer.portal_token_expires_at < now:
        from flask import abort
        abort(410)  # Gone — link expired

    # Tenant settings (for company name/logo)
    _ts = TenantSettings.query.filter_by(tenant_id=customer.tenant_id).all()
    settings = {s.key: s.value for s in _ts}

    # ── Active tracking items (reserved / pending / delivered=ready) ──
    tracking = (
        CustomerOrderTracking.query
        .filter_by(customer_id=customer.id)
        .filter(CustomerOrderTracking.status.in_(['reserved', 'pending', 'delivered']))
        .order_by(CustomerOrderTracking.reserved_date.desc())
        .all()
    )

    # ── Order history ────────────────────────────────────────────
    orders = (
        Order.query
        .filter_by(customer_id=customer.id)
        .order_by(Order.created_at.desc())
        .all()
    )

    # Build safe order rows (no prices)
    order_rows = []
    for order in orders:
        items = []
        for tx in order.sale_transactions:
            pi = tx.product_instance
            if not pi:
                continue
            prod = pi.product
            items.append({
                'model':    prod.model if prod else '—',
                'item_name': prod.item_name if prod else '—',
                'cpu':      prod.cpu if prod else '',
                'ram':      prod.ram if prod else '',
                'serial':   _mask_serial(pi.serial),
                'status':   pi.status,
                'date_sold': tx.date_sold,
            })
        order_rows.append({
            'order_number': order.order_number,
            'created_at':   order.created_at,
            'items':        items,
        })

    return render_template(
        'customer_portal.html',
        customer=customer,
        settings=settings,
        tracking=tracking,
        order_rows=order_rows,
    )


def _mask_serial(serial):
    """Show last 4 characters of serial, mask the rest."""
    if not serial:
        return '—'
    visible = serial[-4:]
    return '•' * max(0, len(serial) - 4) + visible


# ─────────────────────────────────────────────────────────────
# Generate / return portal token (AJAX, staff only)
# ─────────────────────────────────────────────────────────────
@customers_bp.route('/customers/<int:customer_id>/portal_token', methods=['POST'])
@login_required
@module_required('customers', 'full')
def generate_portal_token(customer_id):
    import secrets
    customer = Customer.query.filter_by(
        id=customer_id, tenant_id=current_user.tenant_id
    ).first_or_404()

    regenerate = request.args.get('regenerate') or (request.json or {}).get('regenerate')
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    token_expired = (
        customer.portal_token_expires_at and
        customer.portal_token_expires_at < now
    )
    if not customer.portal_token or regenerate or token_expired:
        customer.portal_token = secrets.token_urlsafe(32)
        customer.portal_token_expires_at = now + timedelta(days=30)
        db.session.commit()

    portal_url = url_for('customers_bp.customer_portal',
                         token=customer.portal_token, _external=True)
    return jsonify({'success': True, 'url': portal_url})


# ─────────────────────────────────────────────────────────────
# Email portal link to customer (AJAX, staff only)
# ─────────────────────────────────────────────────────────────
@customers_bp.route('/customers/<int:customer_id>/send_portal_link', methods=['POST'])
@login_required
@module_required('customers', 'full')
def send_portal_link(customer_id):
    from inventory_flask_app import mail
    from flask_mail import Message
    from inventory_flask_app.models import TenantSettings

    customer = Customer.query.filter_by(
        id=customer_id, tenant_id=current_user.tenant_id
    ).first_or_404()

    if not customer.email:
        return jsonify(success=False, message='Customer has no email address on file.'), 422

    data = request.get_json() or {}
    portal_url = data.get('url') or url_for(
        'customers_bp.customer_portal', token=customer.portal_token, _external=True
    )

    _ts = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in _ts}
    company = settings.get('invoice_title') or settings.get('dashboard_name') or 'Us'

    try:
        body = (
            f"Dear {customer.name},\n\n"
            f"You can track your reservations and order history here:\n\n"
            f"  {portal_url}\n\n"
            f"This link is unique to your account — please do not share it.\n\n"
            f"Best regards,\n{company}\n"
        )
        msg = Message(
            subject=f"Your order portal — {company}",
            recipients=[customer.email],
            body=body,
        )
        mail.send(msg)
        # Log communication
        try:
            from inventory_flask_app.models import CustomerCommunication
            comm = CustomerCommunication(
                tenant_id=current_user.tenant_id,
                customer_id=customer.id,
                type='portal_link',
                subject=f"Your order portal — {company}",
                sent_by=current_user.id,
            )
            db.session.add(comm)
            db.session.commit()
        except Exception as _ce:
            logger.warning("Failed to log portal link communication: %s", _ce)
        return jsonify(success=True, message=f'Portal link emailed to {customer.email}.')
    except Exception as e:
        logger.error('Failed to send portal link to %s: %s', customer.email, e)
        return jsonify(success=False, message=f'Email failed: {e}'), 500
