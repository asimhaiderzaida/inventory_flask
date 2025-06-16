from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required
from ..models import db, Customer, ProductInstance, SaleTransaction

sales_bp = Blueprint('sales_bp', __name__)

@sales_bp.route('/create_sale_form', methods=['GET'])
@login_required
def create_sale_form():
    customers = Customer.query.all()
    # Get serials from query params (?serials=SN1&serials=SN2)
    serials = request.args.getlist('serials')
    selected_instances = []
    if serials:
        selected_instances = ProductInstance.query.filter(ProductInstance.serial_number.in_(serials)).all()
    # Only include available (not sold) product instances in your frontend (if you list them here)
    # If you use AJAX to get product by serial, be sure to check is_sold status in that endpoint too!
    selected_customer_id = request.args.get('customer_id')
    return render_template(
        'create_sale.html',
        customers=customers,
        selected_instances=selected_instances,
        selected_customer_id=selected_customer_id
    )

@sales_bp.route('/confirm_sale', methods=['POST'])
@login_required
def confirm_sale():
    try:
        from ..models import Invoice  # Import here to avoid circular import if needed
        serials = request.form.getlist('serials')
        customer_id = request.form.get('customer_id')
        from flask_login import current_user
        user_id = current_user.id

        if not serials or not customer_id:
            return jsonify({"error": "No products or customer selected."})

        instances = ProductInstance.query.filter(ProductInstance.serial_number.in_(serials)).all()
        customer = db.session.get(Customer, customer_id)

        if not instances or not customer:
            return jsonify({"error": "Invalid data. Please try again."})

        total_amount = 0
        sale_transactions = []
        items = []

        # Build list of sale items and calculate total
        for instance in instances:
            if not instance.is_sold:
                price = float(request.form.get(f"price_{instance.serial_number}", 0))
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
                    'serial_number': instance.serial_number,
                    'product': instance.product if hasattr(instance, 'product') else None,
                    'price_at_sale': price
                })

        if not sale_transactions:
            return jsonify({"error": "No valid products to sell."})

        # Commit sales first to get their IDs
        db.session.commit()

        # Create a new invoice and link sale transactions to it
        invoice = Invoice(
            customer_id=customer.id,
            created_at=datetime.now()
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

@sales_bp.route('/preview_invoice', methods=['POST'])
@login_required
def preview_invoice():
    print("PREVIEW INVOICE DATA:", request.get_json())
    data = request.get_json()
    customer_id = data.get('customer_id')
    items = data.get('items', [])

    # Remap alternative keys
    for item in items:
        if 'product_name' not in item and 'name' in item:
            item['product_name'] = item['name']
        if 'processor' not in item and 'cpu' in item:
            item['processor'] = item['cpu']
        if 'video_card' not in item and 'gpu' in item:
            item['video_card'] = item['gpu']
        if 'resolution' not in item and 'screen' in item:
            item['resolution'] = item['screen']

    for item in items:
        if 'quantity' not in item or not item['quantity']:
            item['quantity'] = 1
        if 'price_at_sale' not in item or not item['price_at_sale']:
            item['price_at_sale'] = float(item.get('price', 0))

    customer = Customer.query.get(customer_id)
    if not customer or not items:
        return "<h3 style='color:red;'>Missing customer or products for preview.</h3>"

    # Fake sale date and invoice number (since not saved)
    fake_invoice_number = "PREVIEW-" + datetime.now().strftime('%Y%m%d%H%M%S')

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
        if not item.get('product_name') and item.get('name'):
            item['product_name'] = item['name']

    for item in items:
        # Pick correct field names and support variations from cart data
        model = item.get('model_number', '') or item.get('model', '') or ''
        processor = item.get('processor', '') or item.get('cpu', '') or ''
        ram = item.get('ram', '')
        storage = item.get('storage', '')
        vga = item.get('video_card', '') or item.get('gpu', '')

        specs_parts = [model]
        if processor: specs_parts.append(processor)
        if ram: specs_parts.append(ram)
        if storage: specs_parts.append(storage)
        if vga: specs_parts.append(vga)
        item['specs'] = " / ".join(specs_parts)

    return render_template(
        'invoice_template.html',
        invoice_number=fake_invoice_number,
        sale_date=datetime.now().strftime('%d-%b-%Y'),
        customer=customer,
        items=items,
        subtotal=subtotal,
        total_vat=total_vat,
        grand_total=grand_total,
        is_preview=True  # You can use this in your template for "DRAFT" watermark etc.
    )

@sales_bp.route('/get_product_by_serial/<serial>')
@login_required
def get_product_by_serial(serial):
    instance = ProductInstance.query.filter_by(serial_number=serial).first()
    if not instance or not instance.product:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "serial_number": instance.serial_number,
        "product_name": instance.product.name,
        "name": instance.product.name,
        "model_number": instance.product.model_number,
        "processor": instance.product.processor,
        "ram": instance.product.ram,
        "storage": instance.product.storage,
        "screen_size": instance.product.screen_size,
        "resolution": instance.product.resolution,
        "grade": instance.product.grade,
        "video_card": instance.product.video_card,
    })