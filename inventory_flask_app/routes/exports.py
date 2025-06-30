from flask import Blueprint, request, jsonify, send_file, render_template, redirect, flash, url_for
from flask_login import login_required
from ..models import db, Product, CustomerOrderTracking, Customer
from datetime import datetime
from io import BytesIO, StringIO
import pandas as pd
import csv
from inventory_flask_app import csrf
from inventory_flask_app.utils import get_now_for_tenant

exports_bp = Blueprint('exports_bp', __name__)

@csrf.exempt
@exports_bp.route('/export-products', methods=['GET'])
@login_required
def export_products():
    from inventory_flask_app.models import ProductInstance
    from flask_login import current_user
    instances = ProductInstance.query.join(Product).filter(Product.tenant_id == current_user.tenant_id).all()

    from inventory_flask_app.models import TenantSettings
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}
    if settings.get('enable_export_module') != 'true':
        flash("Export module is disabled for your tenant.", "warning")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    if not instances:
        flash("No product instances found for export.", "warning")
        return redirect(url_for('dashboard_bp.main_dashboard'))

    # Tenant-specific column visibility and labels
    visible_columns = {
        "Asset": ("asset", settings.get("show_column_asset") == "true", settings.get("label_asset", "Asset")),
        "Serial": ("serial", settings.get("show_column_serial") == "true", settings.get("label_serial", "Serial")),
        "Item Name": ("product.item_name", settings.get("show_column_Item Name") == "true", settings.get("label_item_name", "Item Name")),
        "Make": ("product.make", settings.get("show_column_make") == "true", settings.get("label_make", "Make")),
        "Model": ("product.model", settings.get("show_column_model") == "true", settings.get("label_model", "Model")),
        "CPU": ("product.cpu", settings.get("show_column_cpu") == "true", settings.get("label_cpu", "CPU")),
        "RAM": ("product.ram", settings.get("show_column_ram") == "true", settings.get("label_ram", "RAM")),
        "Disk 1 Size": ("product.disk1size", settings.get("show_column_disk1size") == "true", settings.get("label_disk1size", "Disk 1 Size")),
        "Display": ("product.display", settings.get("show_column_display") == "true", settings.get("label_display", "Display")),
        "GPU 1": ("product.gpu1", settings.get("show_column_gpu1") == "true", settings.get("label_gpu1", "GPU 1")),
        "GPU 2": ("product.gpu2", settings.get("show_column_gpu2") == "true", settings.get("label_gpu2", "GPU 2")),
        "Grade": ("product.grade", settings.get("show_column_Grade") == "true", settings.get("label_grade", "Grade")),
        "Location": ("location.name", settings.get("show_column_location") == "true", settings.get("label_location", "Location")),
    }

    data = []
    for i in instances:
        row = {}
        row["Asset"] = i.asset
        for field_label, (attr_path, visible, custom_label) in visible_columns.items():
            if visible:
                if "." in attr_path:
                    parent, attr = attr_path.split(".")
                    val = getattr(getattr(i, parent, None), attr, '') if getattr(i, parent, None) else ''
                else:
                    val = getattr(i, attr_path, '')
                row[custom_label] = val
        data.append(row)

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

@csrf.exempt
@exports_bp.route('/customer_orders/export')
@login_required
def export_customer_orders():
    from flask_login import current_user

    visible_columns = [
        ("Asset", "asset", "label_asset", "show_column_asset"),
        ("Serial", "serial", "label_serial", "show_column_serial"),
        ("Item Name", "item_name", "label_item_name", "show_column_Item Name"),
        ("Make", "make", "label_make", "show_column_make"),
        ("Model", "model", "label_model", "show_column_model"),
        ("CPU", "cpu", "label_cpu", "show_column_cpu"),
        ("RAM", "ram", "label_ram", "show_column_ram"),
        ("Disk 1 Size", "disk1size", "label_disk1size", "show_column_disk1size"),
        ("Display", "display", "label_display", "show_column_display"),
        ("GPU 1", "gpu1", "label_gpu1", "show_column_gpu1"),
        ("GPU 2", "gpu2", "label_gpu2", "show_column_gpu2"),
        ("Grade", "grade", "label_grade", "show_column_Grade"),
        ("Location", "location", "label_location", "show_column_location"),
        ("Status", "status", "label_status", "show_column_status"),
        ("Stage", "process_stage", "label_stage", "show_column_process_stage"),
        ("Team", "team_assigned", "label_team", "show_column_team"),
        ("Reserved Date", "reserved_date", "label_reserved_date", "show_column_reserved_date"),
        ("Delivered Date", "delivered_date", "label_delivered_date", "show_column_delivered_date")
    ]

    invoice_id = request.args.get('invoice_id')
    customer_id = request.args.get('customer_id')

    from inventory_flask_app.models import TenantSettings
    tenant_settings = TenantSettings.query.filter_by(tenant_id=current_user.tenant_id).all()
    settings = {s.key: s.value for s in tenant_settings}

    data = []
    if invoice_id:
        from inventory_flask_app.models import Invoice, ProductInstance, Product
        from flask_login import current_user
        invoice = Invoice.query.filter_by(id=invoice_id, tenant_id=current_user.tenant_id).first()
        if invoice:
            for sale in invoice.items:
                instance = ProductInstance.query.join(Product).filter(
                    ProductInstance.id == sale.product_instance_id,
                    Product.tenant_id == current_user.tenant_id
                ).first()
                product = Product.query.filter_by(id=instance.product_id, tenant_id=current_user.tenant_id).first() if instance else None
                data.append({
                    'Asset': instance.asset if instance else '',
                    'Serial': instance.serial if instance else '',
                    'Item Name': product.item_name if product else '',
                    'Make': product.make if product else '',
                    'Model': product.model if product else '',
                    'CPU': product.cpu if product else '',
                    'RAM': product.ram if product else '',
                    'Disk 1 Size': product.disk1size if product else '',
                    'Display': product.display if product else '',
                    'GPU 1': product.gpu1 if product else '',
                    'GPU 2': product.gpu2 if product else '',
                    'Grade': product.grade if product else '',
                    'Location': instance.location.name if instance and instance.location else '',
                    'Status': instance.status if instance else '',
                    'Price': sale.price_at_sale,
                    'Date Sold': sale.date_sold.strftime('%Y-%m-%d') if sale.date_sold else ''
                })
    else:
        query = CustomerOrderTracking.query.join(Customer).filter(Customer.tenant_id == current_user.tenant_id)
        if customer_id:
            query = query.filter_by(customer_id=customer_id)
        orders = query.all()

        headers = [settings.get(label_key, default) for default, _, label_key, visible_key in visible_columns if settings.get(visible_key, 'true') == 'true']

        for order in orders:
            product = order.product_instance.product if order.product_instance and order.product_instance.product else None
            # Prepare a temporary object with attributes for easier getattr calls
            class TempObj:
                pass
            temp = TempObj()
            temp.asset = order.product_instance.asset if order.product_instance else ''
            temp.serial = order.product_instance.serial if order.product_instance else ''
            temp.item_name = product.item_name if product else ''
            temp.make = product.make if product else ''
            temp.model = product.model if product else ''
            temp.cpu = product.cpu if product else ''
            temp.ram = product.ram if product else ''
            temp.disk1size = product.disk1size if product else ''
            temp.display = product.display if product else ''
            temp.gpu1 = product.gpu1 if product else ''
            temp.gpu2 = product.gpu2 if product else ''
            temp.grade = product.grade if product else ''
            temp.location = order.product_instance.location.name if order.product_instance and order.product_instance.location else ''
            temp.status = order.status
            temp.process_stage = order.process_stage
            temp.team_assigned = order.team_assigned
            temp.reserved_date = order.reserved_date
            temp.delivered_date = order.delivered_date

            row = []
            for _, field, _, visible_key in visible_columns:
                if settings.get(visible_key, 'true') == 'true':
                    value = getattr(temp, field, '')
                    if field in ['reserved_date', 'delivered_date'] and value:
                        value = value.strftime('%Y-%m-%d')
                    row.append(value)
            data.append(dict(zip(headers, row)))

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if invoice_id:
            df.to_excel(writer, index=False, sheet_name='Invoice Items')
        else:
            df.to_excel(writer, index=False, sheet_name='Customer Orders')
    output.seek(0)
    return send_file(output, download_name='customer_orders.xlsx', as_attachment=True)

@csrf.exempt
@exports_bp.route('/inventory/export', methods=['GET', 'POST'])
@login_required
def inventory_export():
    from flask_login import current_user

    if request.method == 'POST':  
        model = request.form.get('model')
        processor = request.form.get('processor')
        gpu1 = request.form.get('gpu1')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        serial_raw = request.form.get('serial')
        action = request.form.get('action')
        
        query = Product.query.filter_by(tenant_id=current_user.tenant_id)

        if serial_raw:
            serials = [s.strip() for s in serial_raw.replace('\n', ',').split(',') if s.strip()]
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    Product.serial.in_(serials),
                    Product.asset.in_(serials)
                )
            )
        else:
            if model:
                query = query.filter(Product.model.ilike(f"%{model}%"))
            if processor:
                query = query.filter(Product.processor.ilike(f"%{processor}%"))
            if gpu1:
                query = query.filter(Product.gpu1.ilike(f"%{gpu1}%"))
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
            "Item Name": p.item_name,
            "Asset": p.asset,
            "Serial": p.serial,
            "Model": p.model,
            "Make": p.make,
            "CPU": p.cpu,
            "RAM": p.ram,
            "Disk 1 Size": p.disk1size,
            "Display": p.display,
            "GPU 1": p.gpu1,
            "GPU 2": p.gpu2,
            "Grade": p.grade,
            "Location": p.location.name if p.location else '',
            "Created At": p.created_at.astimezone(get_now_for_tenant().tzinfo).strftime('%Y-%m-%d') if p.created_at else ''
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
