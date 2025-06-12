from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from ..models import db, Vendor

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
    return render_template('vendor_profile.html', vendor=vendor, purchase_orders=purchase_orders)


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
from flask import send_file
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