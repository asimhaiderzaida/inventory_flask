import json
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_paginate import Pagination, get_page_args
from flask_login import login_required, current_user
from ..models import db, Customer, ProductInstance, SaleTransaction, Product, TenantSettings
from sqlalchemy import or_
from inventory_flask_app import csrf
from inventory_flask_app.utils import get_now_for_tenant

logger = logging.getLogger(__name__)


sales_bp = Blueprint('sales_bp', __name__)

@sales_bp.route('/sales')
@login_required
def sales_index():
    return render_template('sales_index.html')


@sales_bp.route('/api/search_units')
@login_required
def search_units_api():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    tid = current_user.tenant_id
    instances = (
        ProductInstance.query
        .join(Product)
        .filter(
            Product.tenant_id == tid,
            ProductInstance.is_sold == False,
            ProductInstance.status != 'idle',
            db.or_(
                ProductInstance.serial.ilike(f'%{q}%'),
                ProductInstance.asset.ilike(f'%{q}%'),
                Product.model.ilike(f'%{q}%'),
            )
        )
        .options(db.joinedload(ProductInstance.product))
        .limit(20)
        .all()
    )
    return jsonify([{
        'id': i.id,
        'text': f"{i.product.model or ''} | {i.serial}",
        'serial': i.serial,
        'asset': i.asset or '',
        'model': i.product.model or '',
        'make': i.product.make or '',
        'cpu': i.product.cpu or '',
        'ram': i.product.ram or '',
        'status': i.status,
        'asking_price': float(i.asking_price) if i.asking_price else None,
    } for i in instances])


@sales_bp.route('/create_sale_form', methods=['GET'])
@login_required
def create_sale_form():
    customers = Customer.query.filter_by(tenant_id=current_user.tenant_id).all()
    serial_asset_pairs = list(zip(
        request.args.getlist('serials'),
        request.args.getlist('assets')
    ))
    selected_instances = []
    for serial, asset in serial_asset_pairs:
        instance = ProductInstance.query.join(Product).filter(
            ProductInstance.serial == serial,
            ProductInstance.asset == asset,
            Product.tenant_id == current_user.tenant_id
        ).first()
        if instance:
            selected_instances.append(instance)

    selected_customer_id = request.args.get('customer_id')
    _ts = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings_dict = {s.key: s.value for s in _ts}
    return render_template(
        'create_sale.html',
        customers=customers,
        selected_instances=selected_instances,
        available_serials_data=[],
        selected_customer_id=selected_customer_id,
        settings=settings_dict,
    )
@sales_bp.route('/confirm_sale', methods=['POST'])
@login_required
def confirm_sale():
    try:
        from ..models import Invoice, SaleItem, Order
        scanned_sale = session.get('scanned_sale', [])
        logger.debug("Received scanned unit count: %d", len(scanned_sale))
        customer_id = request.form.get('customer_id')
        user_id = current_user.id

        if not scanned_sale or not customer_id:
            return jsonify({"error": "No products or customer selected."})

        serial_asset_pairs = [(item.get("serial"), item.get("asset")) for item in scanned_sale]
        instances = []
        for serial, asset in serial_asset_pairs:
            instance = ProductInstance.query.join(Product).filter(
                ProductInstance.serial == serial,
                ProductInstance.asset == asset,
                Product.tenant_id == current_user.tenant_id
            ).first()
            if instance:
                instances.append(instance)
        customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first()

        if not customer:
            return jsonify({"error": "Unauthorized customer access"}), 403

        if not instances:
            return jsonify({"error": "Invalid data. Please try again."})

        now = get_now_for_tenant()
        order_number = f"ORD-{now.strftime('%Y%m%d%H%M%S')}"
        new_order = Order(
            order_number=order_number,
            customer_id=customer.id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id
        )
        db.session.add(new_order)
        db.session.flush()  # get new_order.id without extra commit

        sale_transactions = []

        for instance in instances:
            if not instance.is_sold:
                price = float(request.form.get(f"price_{instance.serial}", 0))
                sale = SaleTransaction(
                    product_instance_id=instance.id,
                    customer_id=customer.id,
                    user_id=user_id,
                    price_at_sale=price,
                    notes=""
                )
                sale.order_id = new_order.id
                instance.is_sold = True
                db.session.add(sale)
                sale_transactions.append(sale)

        if not sale_transactions:
            return jsonify({"error": "No valid products to sell."})

        # Flush to get sale IDs
        db.session.flush()

        # Create invoice
        invoice = Invoice(
            customer_id=customer.id,
            tenant_id=current_user.tenant_id,
            created_at=now
        )
        db.session.add(invoice)
        db.session.flush()  # get invoice.id

        # Assign invoice number, payment info, and link sales
        payment_method = request.form.get('payment_method', 'cash')
        invoice.invoice_number = f"INV-{invoice.id:05d}"
        invoice.payment_method = payment_method
        invoice.payment_status = 'pending' if payment_method == 'credit' else 'paid'
        for sale in sale_transactions:
            sale.invoice_id = invoice.id
            sale.payment_method = payment_method
            sale.payment_status = 'pending' if payment_method == 'credit' else 'paid'

        # Determine VAT rate for this sale
        vat_applied = request.form.get('vat_applied', 'true') == 'true'
        if vat_applied:
            _ts = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
            vat_rate = float({s.key: s.value for s in _ts}.get('vat_rate') or 5)
        else:
            vat_rate = 0.0

        for sale in sale_transactions:
            db.session.add(SaleItem(
                sale_id=sale.id,
                product_instance_id=sale.product_instance_id,
                price_at_sale=sale.price_at_sale if sale.price_at_sale is not None else 0,
                vat_rate=vat_rate,
                invoice_id=invoice.id
            ))

        db.session.commit()

        # Auto-create AccountReceivable for credit sales
        if payment_method == 'credit':
            from ..models import AccountReceivable
            from decimal import Decimal as _Decimal
            _settings_list = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
            _settings_dict = {s.key: s.value for s in _settings_list}
            _currency = _settings_dict.get('currency') or 'AED'
            total_due = sum(
                float(s.price_at_sale or 0) * (1 + vat_rate / 100)
                for s in sale_transactions
            )
            credit_due_date = None
            _due_str = request.form.get('credit_due_date', '').strip()
            if _due_str:
                try:
                    credit_due_date = datetime.strptime(_due_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            ar = AccountReceivable(
                tenant_id=current_user.tenant_id,
                customer_id=customer.id,
                invoice_id=invoice.id,
                sale_id=new_order.id,
                amount_due=_Decimal(str(round(total_due, 2))),
                amount_paid=_Decimal('0'),
                currency=_currency,
                due_date=credit_due_date,
                status='open',
            )
            db.session.add(ar)
            db.session.commit()

        session.pop('scanned_sale', None)

        return jsonify({"success": True, "invoice_url": url_for('invoices_bp.download_invoice', invoice_id=invoice.id)})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to confirm sale: {str(e)}"})


@sales_bp.route('/preview_invoice', methods=['POST'])
@login_required
def preview_invoice():
    logger.debug("Preview invoice data received")
    data = request.get_json()
    customer_id = data.get('customer_id')
    items = data.get('items', [])

    # Remap alternative keys to unified structure
    for item in items:
        item['product_name'] = item.get('product_name') or item.get('name') or item.get('item_name')
        item['cpu'] = item.get('cpu') or item.get('processor')
        item['gpu1'] = item.get('gpu1') or item.get('gpu') or item.get('video_card')
        item['model'] = item.get('model') or item.get('model_number')
        item['serial'] = item.get('serial') or ''
        item['asset'] = item.get('asset') or ''

    for item in items:
        if 'quantity' not in item or not item['quantity']:
            item['quantity'] = 1
        if 'price_at_sale' not in item or not item['price_at_sale']:
            item['price_at_sale'] = float(item.get('price', 0))

    customer = Customer.query.filter_by(id=customer_id, tenant_id=current_user.tenant_id).first()
    if not customer or not items:
        return "<h3 style='color:red;'>Missing customer or products for preview.</h3>"

    fake_invoice_number = "PREVIEW-" + get_now_for_tenant().strftime('%Y%m%d%H%M%S')

    for item in items:
        # Pick correct field names and support variations from cart data
        specs_parts = [
            item.get('model', ''),
            item.get('cpu', ''),
            item.get('ram', ''),
            item.get('disk1size', ''),
            item.get('display', ''),
            item.get('gpu1', ''),
            item.get('gpu2', ''),
            item.get('grade', ''),
        ]
        item['specs'] = " / ".join(filter(None, specs_parts))

    _tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings_dict = {s.key: s.value for s in _tenant_settings}
    vat_rate = float(settings_dict.get('vat_rate') or 5)

    # Recalculate totals with tenant vat_rate
    subtotal = total_vat = grand_total = 0
    for item in items:
        qty = item.get('quantity', 1)
        price = float(item.get('price_at_sale', 0) or 0)
        line_total = price * qty
        vat_amount = line_total * (vat_rate / 100)
        subtotal += line_total
        total_vat += vat_amount
        grand_total += line_total + vat_amount

    return render_template(
        'invoice_template.html',
        invoice_number=fake_invoice_number,
        sale_date=get_now_for_tenant().strftime('%d-%b-%Y'),
        customer=customer,
        items=items,
        subtotal=subtotal,
        total_vat=total_vat,
        grand_total=grand_total,
        is_preview=True,
        settings=settings_dict
    )


@sales_bp.route('/sales/sold_units')
@login_required
def sold_units_view():
    from ..models import SaleItem

    customer_filter = request.args.get('customer')
    sale_date_filter = request.args.get('sale_date')
    model_filter = request.args.get('model', '').strip()
    cpu_filter = request.args.get('cpu', '').strip()

    # Use explicit joins to avoid ORM ambiguity
    query = SaleItem.query \
        .join(SaleTransaction, SaleItem.sale_id == SaleTransaction.id) \
        .join(ProductInstance, SaleItem.product_instance_id == ProductInstance.id) \
        .join(Product, ProductInstance.product_id == Product.id) \
        .filter(Product.tenant_id == current_user.tenant_id)

    if customer_filter:
        query = query.filter(SaleTransaction.customer_id == customer_filter)
    if sale_date_filter:
        query = query.filter(SaleTransaction.date_sold.like(f"{sale_date_filter}%"))
    if model_filter:
        query = query.filter(Product.model.ilike(f"%{model_filter}%"))
    if cpu_filter:
        query = query.filter(Product.cpu.ilike(f"%{cpu_filter}%"))

    # Pagination logic
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page')
    per_page = 50  # Or adjust based on preference
    total = query.count()
    sold_items = query.order_by(SaleTransaction.id.desc()).offset(offset).limit(per_page).all()
    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5')

    # Query customers for the template
    customers = Customer.query.filter_by(tenant_id=current_user.tenant_id).all()

    return render_template(
        "sold_items.html",
        sold_data=sold_items,
        selected_customer=customer_filter,
        selected_date=sale_date_filter,
        customers=customers,
        pagination=pagination
    )

@sales_bp.route('/scan_add', methods=['POST'])
@login_required
def scan_add():
    from flask import jsonify
    data = request.get_json()

    if not data or not data.get("serial"):
        return jsonify({"error": "Missing serial"}), 400

    scanned = session.get('scanned_sale', [])
    serials = [s.get('serial') for s in scanned]
    if data["serial"] not in serials:
        scanned.append(data)
        session['scanned_sale'] = scanned

    return jsonify({"message": "Scanned unit added", "count": len(scanned)})


@sales_bp.route('/load_scanned_units', methods=['GET'])
@login_required
def load_scanned_units():
    from flask import jsonify
    scanned = session.get('scanned_sale', [])
    return jsonify(scanned)


@sales_bp.route('/clear_scanned_units', methods=['POST'])
@login_required
def clear_scanned_units():
    session.pop('scanned_sale', None)
    return jsonify({"success": True})


# Excel export route for filtered sold units
@sales_bp.route('/sales/export_sold_units')
@login_required
def export_sold_units():
    from openpyxl import Workbook
    from io import BytesIO
    from flask import send_file

    customer_filter = request.args.get('customer')
    sale_date_filter = request.args.get('sale_date')
    model_filter = request.args.get('model')
    cpu_filter = request.args.get('cpu')

    from ..models import SaleItem
    query = SaleItem.query \
        .join(SaleTransaction, SaleItem.sale_id == SaleTransaction.id) \
        .join(ProductInstance, SaleItem.product_instance_id == ProductInstance.id) \
        .join(Product, ProductInstance.product_id == Product.id) \
        .filter(Product.tenant_id == current_user.tenant_id)

    if customer_filter:
        query = query.filter(SaleTransaction.customer_id == customer_filter)
    if sale_date_filter:
        query = query.filter(SaleTransaction.date_sold.like(f"{sale_date_filter}%"))
    if model_filter:
        query = query.filter(Product.model.ilike(f"%{model_filter}%"))
    if cpu_filter:
        query = query.filter(Product.cpu.ilike(f"%{cpu_filter}%"))

    items = query.all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Sold Units"
    ws.append(["Serial", "Asset", "Model", "CPU", "RAM", "Disk", "Display", "Customer", "Sale Date", "Price", "Payment", "Invoice"])

    for item in items:
        u = item.product_instance
        sale = item.sale_transaction
        inv = sale.invoice if sale else None
        ws.append([
            u.serial if u else '',
            u.asset if u else '',
            u.product.model if u and u.product else '',
            u.product.cpu if u and u.product else '',
            u.product.ram if u and u.product else '',
            u.product.disk1size if u and u.product else '',
            u.product.display if u and u.product else '',
            sale.customer.name if sale and sale.customer else '',
            sale.date_sold.strftime("%Y-%m-%d") if sale and sale.date_sold else '',
            item.price_at_sale,
            inv.payment_method or '' if inv else '',
            inv.invoice_number or '' if inv else '',
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="sold_units_export.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
