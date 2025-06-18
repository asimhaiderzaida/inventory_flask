from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required
from ..models import db, Vendor
import pandas as pd
import io

vendors_bp = Blueprint('vendors_bp', __name__)

@vendors_bp.route('/vendors/add', methods=['GET', 'POST'])
@login_required
def add_vendor():
    if request.method == 'POST':
        name = request.form.get('name')
        contact = request.form.get('contact')
        if not name:
            flash('Vendor name is required.', 'error')
            return redirect(request.url)
        existing_vendor = Vendor.query.filter_by(name=name.strip()).first()
        if existing_vendor:
            flash('Vendor already exists.', 'warning')
            return redirect(url_for('dashboard_bp.main_dashboard'))
        vendor = Vendor(name=name.strip(), contact=contact.strip() if contact else None)
        db.session.add(vendor)
        db.session.commit()
        flash(f"✅ Vendor '{name}' added successfully!", 'success')
        return redirect(url_for('dashboard_bp.main_dashboard'))

    return render_template('add_vendor.html')
@vendors_bp.route('/vendors/center')
@login_required
def vendor_center():
    search = request.args.get('search', '').strip()
    query = Vendor.query
    if search:
        query = query.filter(Vendor.name.ilike(f"%{search}%"))
    vendors = query.order_by(Vendor.name).all()
    return render_template('vendor_center.html', vendors=vendors, search=search)

print("Loading vendors.py - before vendor_profile route")  # At the top
@vendors_bp.route('/vendors/<int:vendor_id>/profile')
@login_required
def vendor_profile(vendor_id):
    print("Registering vendor_profile route")  # Right before @vendors_bp.route('/vendors/<int:vendor_id>/profile')
    vendor = Vendor.query.get_or_404(vendor_id)
    # Get all purchase orders for this vendor
    from inventory_flask_app.models import PurchaseOrder
    purchase_orders = PurchaseOrder.query.filter_by(vendor_id=vendor.id).order_by(PurchaseOrder.created_at.desc()).all()

    po_list = []
    po_details_map = {}

    for po in purchase_orders:
        units_list = []
        for inst in getattr(po, "instances", []):
            product = inst.product
            units_list.append({
                "serial_number": inst.serial_number,
                "product_name": product.name if product else '',
                "model_number": product.model_number if product else '',
                "ram": product.ram if product else '',
                "processor": product.processor if product else '',
                "storage": product.storage if product else '',
                "screen_size": product.screen_size if product else '',
                "resolution": product.resolution if product else '',
                "grade": product.grade if product else '',
                "video_card": product.video_card if product else '',
                "status": inst.status
            })
        po_list.append({
            "po_id": po.id,
            "po_number": po.po_number or po.id,
            "date": po.created_at,
            "total_units": len(units_list),
            "total_amount": "",  # Add total if available
        })
        po_details_map[po.id] = units_list

    # --- BEGIN Direct Uploads (No PO) logic ---
    from inventory_flask_app.models import ProductInstance, Product
    from collections import defaultdict
    direct_uploads_list = []
    direct_uploads_map = {}
    instances = ProductInstance.query.join(Product).filter(
        Product.vendor_id == vendor.id
    ).all()
    upload_groups = defaultdict(list)
    for inst in instances:
        key = inst.created_at.date() if hasattr(inst, 'created_at') and inst.created_at else 'Unknown'
        upload_groups[key].append(inst)
    for date_key, units in upload_groups.items():
        units_list = []
        for inst in units:
            product = inst.product if inst else None
            units_list.append({
                "serial_number": inst.serial_number,
                "product_name": product.name if product else '',
                "model_number": product.model_number if product else '',
                "ram": product.ram if product else '',
                "processor": product.processor if product else '',
                "storage": product.storage if product else '',
                "screen_size": product.screen_size if product else '',
                "resolution": product.resolution if product else '',
                "grade": product.grade if product else '',
                "video_card": product.video_card if product else '',
                "status": inst.status
            })
        direct_uploads_list.append({
            "upload_date": date_key,
            "total_units": len(units_list),
            "units": units_list,
        })
        direct_uploads_map[date_key] = units_list
    # --- END Direct Uploads (No PO) logic ---

    return render_template(
        'vendor_profile.html',
        vendor=vendor,
        po_list=po_list,
        po_details_map=po_details_map,
        direct_uploads_list=direct_uploads_list,
        direct_uploads_map=direct_uploads_map
    )


# Add edit_vendor route
@vendors_bp.route('/vendors/<int:vendor_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_vendor(vendor_id):
    vendor = Vendor.query.get_or_404(vendor_id)
    if request.method == 'POST':
        vendor.name = request.form.get('name')
        vendor.contact = request.form.get('contact')
        vendor.email = request.form.get('email')
        vendor.company = request.form.get('company')
        vendor.address = request.form.get('address')
        db.session.commit()
        flash('Vendor updated successfully!', 'success')
        return redirect(url_for('vendors_bp.vendor_center'))
    return render_template('edit_vendor.html', vendor=vendor)

from openpyxl import Workbook
from io import BytesIO

@vendors_bp.route('/vendors/<int:vendor_id>/export_po')
@login_required
def export_vendor_po(vendor_id):
    vendor = Vendor.query.get_or_404(vendor_id)
    from inventory_flask_app.models import PurchaseOrder
    purchase_orders = PurchaseOrder.query.filter_by(vendor_id=vendor.id).order_by(PurchaseOrder.created_at.desc()).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Vendor PO History"
    ws.append([
        'PO Number', 'PO Date', 'Serial', 'Product Name', 'Model', 'RAM', 'Processor', 
        'Storage', 'Screen Size', 'Resolution', 'Grade', 'Video Card', 'Status'
    ])
    for po in purchase_orders:
        for inst in getattr(po, "instances", []):
            ws.append([
                po.po_number or po.id,
                po.created_at.strftime('%Y-%m-%d') if po.created_at else '',
                inst.serial_number,
                inst.product.name if inst.product else '',
                inst.product.model_number if inst.product else '',
                inst.product.ram if inst.product else '',
                inst.product.processor if inst.product else '',
                inst.product.storage if inst.product else '',
                inst.product.screen_size if inst.product else '',
                inst.product.resolution if inst.product else '',
                inst.product.grade if inst.product else '',
                inst.product.video_card if inst.product else '',
                inst.status
            ])
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"vendor_{vendor.id}_po_history.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@vendors_bp.route('/vendors/<int:vendor_id>/export_upload')
@login_required
def export_vendor_upload(vendor_id):
    upload_date = request.args.get('upload_date')
    if not upload_date:
        return "No upload date specified.", 400

    from inventory_flask_app.models import ProductInstance, Product
    # Find all instances for this vendor and this upload date
    instances = (
        ProductInstance.query
        .join(Product)
        .filter(Product.vendor_id == vendor_id)
        .filter(db.func.strftime('%Y-%m-%d', ProductInstance.created_at) == upload_date)
        .all()
    )
    data = []
    for inst in instances:
        product = inst.product
        data.append({
            "Serial Number": inst.serial_number,
            "Product Name": product.name if product else '',
            "Model Number": product.model_number if product else '',
            "RAM": product.ram if product else '',
            "Processor": product.processor if product else '',
            "Storage": product.storage if product else '',
            "Screen Size": product.screen_size if product else '',
            "Resolution": product.resolution if product else '',
            "Grade": product.grade if product else '',
            "Video Card": product.video_card if product else '',
            "Status": inst.status,
        })
    if not data:
        return "No units found for this upload.", 404

    df = pd.DataFrame(data)
    out = io.BytesIO()
    df.to_excel(out, index=False)
    out.seek(0)
    return send_file(
        out,
        download_name=f"vendor_{vendor_id}_upload_{upload_date}.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )