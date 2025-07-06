from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required
from flask_login import current_user
from ..models import db, Customer, ProductInstance, SaleTransaction, Product
from sqlalchemy import or_
from inventory_flask_app import csrf
from inventory_flask_app.utils import get_now_for_tenant

sales_bp = Blueprint('sales_bp', __name__)

@csrf.exempt
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

    # Add available unsold product instances for selection in UI
    available_instances = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.is_sold == False
    ).all()

    # Serialize available_instances to a list of dicts for JSON
    available_serials_data = [
        {
            "serial": i.serial,
            "product_instance_id": i.id
        }
        for i in available_instances
    ]

    selected_customer_id = request.args.get('customer_id')
    return render_template(
        'create_sale.html',
        customers=customers,
        selected_instances=selected_instances,
        available_serials_data=available_serials_data,
        selected_customer_id=selected_customer_id
    )
@csrf.exempt
@sales_bp.route('/confirm_sale', methods=['POST'])
@login_required
def confirm_sale():
    try:
        from ..models import Invoice  # Import here to avoid circular import if needed
        serials = request.form.getlist('serials')
        assets = request.form.getlist('assets')
        customer_id = request.form.get('customer_id')
        user_id = current_user.id

        if not serials or not customer_id:
            return jsonify({"error": "No products or customer selected."})

        serial_asset_pairs = list(zip(
            request.form.getlist('serials'),
            request.form.getlist('assets')
        ))
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

        total_amount = 0
        sale_transactions = []
        items = []

        # Build list of sale items and calculate total
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
                instance.is_sold = True
                # Decrement product stock
                if instance.product and hasattr(instance.product, "stock"):
                    if instance.product.stock > 0:
                        instance.product.stock -= 1
                db.session.add(sale)
                sale_transactions.append(sale)
                total_amount += price
                # Add details for invoice item
                items.append({
                    'serial': instance.serial,
                    'asset': instance.asset,
                    'item_name': instance.product.item_name if instance.product else '',
                    'make': instance.product.make if instance.product else '',
                    'model': instance.product.model if instance.product else '',
                    'cpu': instance.product.cpu if instance.product else '',
                    'ram': instance.product.ram if instance.product else '',
                    'disk1size': instance.product.disk1size if instance.product else '',
                    'display': instance.product.display if instance.product else '',
                    'gpu1': instance.product.gpu1 if instance.product else '',
                    'gpu2': instance.product.gpu2 if instance.product else '',
                    'grade': instance.product.grade if instance.product else ''
                })

        if not sale_transactions:
            return jsonify({"error": "No valid products to sell."})

        # Commit sales first to get their IDs
        db.session.commit()

        # --- Ensure each sold unit is recorded in SaleItem ---
        from ..models import SaleItem
        # Create SaleItem for each sale
        for sale in sale_transactions:
            db.session.add(SaleItem(
                sale_transaction_id=sale.id,
                product_instance_id=sale.product_instance_id
            ))
        db.session.commit()
        # --- End SaleItem recording ---

        # Create a new invoice and link sale transactions to it
        invoice = Invoice(
            customer_id=customer.id,
            tenant_id=current_user.tenant_id,
            created_at=get_now_for_tenant()
        )
        db.session.add(invoice)
        db.session.commit()  # To get invoice.id

        # Link sales to invoice
        for sale in sale_transactions:
            sale.invoice_id = invoice.id
        db.session.commit()

        # Clean session
        # Removed session.pop('sale_serials', None)
        # Removed session.pop('customer_id', None)

        return jsonify({"success": True, "invoice_url": url_for('invoices_bp.download_invoice', invoice_id=invoice.id)})

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to confirm sale: {str(e)}"})


import json
from datetime import datetime

@csrf.exempt
@sales_bp.route('/preview_invoice', methods=['POST'])
@login_required
def preview_invoice():
    print("PREVIEW INVOICE DATA:", request.get_json())
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

    customer = Customer.query.get(customer_id)
    if not customer or not items:
        return "<h3 style='color:red;'>Missing customer or products for preview.</h3>"

    # Fake sale date and invoice number (since not saved)
    fake_invoice_number = "PREVIEW-" + get_now_for_tenant().strftime('%Y%m%d%H%M%S')

    subtotal = 0
    total_vat = 0
    grand_total = 0
    vat_rate = 5  # Default VAT

    # Calculate all totals
    for item in items:
        qty = item.get('quantity', 1)
        price = float(item.get('price_at_sale', 0) or 0)
        line_total = price * qty
        vat_amount = line_total * (vat_rate / 100)
        total_with_vat = line_total + vat_amount
        subtotal += line_total
        total_vat += vat_amount
        grand_total += total_with_vat

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

    return render_template(
        'invoice_template.html',
        invoice_number=fake_invoice_number,
        sale_date=get_now_for_tenant().strftime('%d-%b-%Y'),
        customer=customer,
        items=items,
        subtotal=subtotal,
        total_vat=total_vat,
        grand_total=grand_total,
        is_preview=True
    )

@csrf.exempt
@sales_bp.route('/get_product_by_serial/<serial>')
@login_required
def get_product_by_serial(serial):
    serial = serial.strip().upper()
    instance = ProductInstance.query.join(Product).filter(
        or_(
            ProductInstance.serial == serial,
            ProductInstance.asset == serial
        ),
        Product.tenant_id == current_user.tenant_id
    ).first()
    if not instance:
        return jsonify({"error": "Unauthorized access"}), 403
    return jsonify({
        "serial": instance.serial,
        "asset": instance.asset,
        "item_name": instance.product.item_name,
        "name": instance.product.item_name,
        "make": instance.product.make,
        "model": instance.product.model,
        "cpu": instance.product.cpu,
        "ram": instance.product.ram,
        "grade": instance.product.grade,
        "display": instance.product.display,
        "gpu1": instance.product.gpu1,
        "gpu2": instance.product.gpu2,
        "disk1size": instance.product.disk1size
    })


# Route to serve list of sold units for dashboard linking
@csrf.exempt
@sales_bp.route('/sales/sold_units')
@login_required
def sold_units_view():
    sold_units = ProductInstance.query.join(Product).filter(
        Product.tenant_id == current_user.tenant_id,
        ProductInstance.is_sold == True
    ).order_by(ProductInstance.updated_at.desc()).all()

    return render_template("sold_units.html", units=sold_units)