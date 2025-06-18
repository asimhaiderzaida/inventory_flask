from flask import Blueprint, request, jsonify, send_file, render_template, redirect, flash
from flask_login import login_required
from ..models import db, Product, CustomerOrderTracking, Customer
from datetime import datetime
from io import BytesIO, StringIO
import pandas as pd
import csv

exports_bp = Blueprint('exports_bp', __name__)

@exports_bp.route('/export-products', methods=['GET'])
@login_required
def export_products():
    try:
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')

        from inventory_flask_app.models import ProductInstance

        instances = ProductInstance.query.all()

        data = []
        for i in instances:
            data.append({
                "Serial Number": i.serial_number,
                "Product": i.product.name if i.product else '',
                "Model Number": i.product.model_number if i.product else '',
                "Grade": i.product.grade if i.product else '',
                "RAM": i.product.ram if i.product else '',
                "Processor": i.product.processor if i.product else '',
                "Storage": i.product.storage if i.product else '',
                "Screen Size": i.product.screen_size if i.product else '',
                "Resolution": i.product.resolution if i.product else '',
                "Video Card": i.product.video_card if i.product else ''
            })

        df = pd.DataFrame(data)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Products')

        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='product_inventory_export.xlsx'
        )
    except Exception as e:
        return jsonify({"error": f"Failed to export products: {str(e)}"}), 500

@exports_bp.route('/customer_orders/export')
@login_required
def export_customer_orders():
    invoice_id = request.args.get('invoice_id')
    customer_id = request.args.get('customer_id')

    data = []
    if invoice_id:
        from inventory_flask_app.models import Invoice, ProductInstance, Product
        invoice = Invoice.query.get(invoice_id)
        if invoice:
            for sale in invoice.items:
                instance = ProductInstance.query.get(sale.product_instance_id)
                product = Product.query.get(instance.product_id) if instance else None
                data.append({
                    'Serial Number': instance.serial_number if instance else '',
                    'Product Name': product.name if product else '',
                    'Model Number': product.model_number if product else '',
                    'Grade': product.grade if product else '',
                    'RAM': product.ram if product else '',
                    'Processor': product.processor if product else '',
                    'Storage': product.storage if product else '',
                    'Screen Size': product.screen_size if product else '',
                    'Resolution': product.resolution if product else '',
                    'Video Card': product.video_card if product else '',
                    'Status': instance.status if instance else '',
                    'Price': sale.price_at_sale,
                    'Date Sold': sale.date_sold.strftime('%Y-%m-%d') if sale.date_sold else ''
                })
    else:
        query = CustomerOrderTracking.query
        if customer_id:
            query = query.filter_by(customer_id=customer_id)
        orders = query.all()
        for order in orders:
            product = order.product_instance.product if order.product_instance and order.product_instance.product else None
            data.append({
                'Customer': order.customer.name if order.customer else '',
                'Serial Number': order.product_instance.serial_number if order.product_instance else '',
                'Product Name': product.name if product else '',
                'Model Number': product.model_number if product else '',
                'Grade': product.grade if product else '',
                'RAM': product.ram if product else '',
                'Processor': product.processor if product else '',
                'Storage': product.storage if product else '',
                'Screen Size': product.screen_size if product else '',
                'Resolution': product.resolution if product else '',
                'Video Card': product.video_card if product else '',
                'Sale Price': order.price if hasattr(order, "price") else '',
                'Status': order.status,
                'Stage': order.process_stage,
                'Team': order.team_assigned,
                'Reserved Date': order.reserved_date.strftime('%Y-%m-%d'),
                'Delivered Date': order.delivered_date.strftime('%Y-%m-%d') if order.delivered_date else ''
            })

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if invoice_id:
            df.to_excel(writer, index=False, sheet_name='Invoice Items')
        else:
            df.to_excel(writer, index=False, sheet_name='Customer Orders')
    output.seek(0)
    return send_file(output, download_name='customer_orders.xlsx', as_attachment=True)

@exports_bp.route('/inventory/export', methods=['GET', 'POST'])
@login_required
def inventory_export():
    if request.method == 'POST':  
        model = request.form.get('model_number')
        processor = request.form.get('processor')
        video_card = request.form.get('video_card')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        serial_numbers_raw = request.form.get('serial_numbers')
        action = request.form.get('action')
        
        query = Product.query

        if serial_numbers_raw:
            serials = [s.strip() for s in serial_numbers_raw.replace('\n', ',').split(',') if s.strip()]
            query = query.filter(Product.barcode.in_(serials))
        else:
            if model:
                query = query.filter(Product.model_number.ilike(f"%{model}%"))
            if processor:
                query = query.filter(Product.processor.ilike(f"%{processor}%"))
            if video_card:
                query = query.filter(Product.video_card.ilike(f"%{video_card}%"))
            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d')
                    end = datetime.strptime(end_date, '%Y-%m-%d')
                    query = query.filter(Product.created_at.between(start, end))
                except ValueError:
                    flash("Invalid date format. Use YYYY-MM-DD", "error")
                    return redirect('/inventory/export')

        products = query.all()

        data = [{
            "ID": p.id,
            "Name": p.name,
            "Serial Number": p.barcode,
            "Model Number": p.model_number,
            "Processor": p.processor,
            "RAM": p.ram,
            "Storage": p.storage,
            "Screen Size": p.screen_size,
            "Resolution": p.resolution,
            "Grade": p.grade,
            "Video Card": p.video_card,
            "Created At": p.created_at.strftime('%Y-%m-%d') if p.created_at else ''
        } for p in products]

        if action == 'preview':
            return render_template('export_preview.html', products=data)

        if action == 'download':
            output = BytesIO()
            df = pd.DataFrame(data)
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Inventory')
            output.seek(0)
            return send_file(output, as_attachment=True, download_name='inventory_export.xlsx')

    return render_template('inventory_export.html')
