from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required
from ..models import db, Vendor
import pandas as pd
import io

# --- WTForms Vendor Form ---
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Optional

from inventory_flask_app.utils import get_now_for_tenant

class VendorForm(FlaskForm):
    name = StringField('Vendor Name', validators=[DataRequired()])
    contact = StringField('Contact', validators=[Optional()])
    email = StringField('Email', validators=[Optional()])
    phone = StringField('Phone', validators=[Optional()])
    address = StringField('Address', validators=[Optional()])

vendors_bp = Blueprint('vendors_bp', __name__)

# --- CSRF Protection ---
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect()

@vendors_bp.route('/vendors/add', methods=['GET', 'POST'])
@login_required
def add_vendor():
    from flask_login import current_user
    form = VendorForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        contact = form.contact.data.strip() if form.contact.data else None
        existing_vendor = Vendor.query.filter_by(name=name, tenant_id=current_user.tenant_id).first()
        if existing_vendor:
            flash('Vendor already exists.', 'warning')
            next_url = request.args.get('next')
            return redirect(next_url) if next_url else redirect(url_for('vendors_bp.vendor_center'))
        vendor = Vendor(
            name=name,
            contact=contact,
            email=form.email.data.strip() if form.email.data else None,
            phone=form.phone.data.strip() if form.phone.data else None,
            address=form.address.data.strip() if form.address.data else None,
            tenant_id=current_user.tenant_id
        )
        db.session.add(vendor)
        db.session.commit()
        flash(f"✅ Vendor '{name}' added successfully!", 'success')
        next_url = request.args.get('next')
        return redirect(next_url) if next_url else redirect(url_for('vendors_bp.vendor_center'))
    return render_template('add_vendor.html', form=form)
@vendors_bp.route('/vendors/center')
@login_required
def vendor_center():
    from flask_login import current_user
    search = request.args.get('search', '').strip()
    query = Vendor.query.filter_by(tenant_id=current_user.tenant_id)
    if search:
        query = query.filter(Vendor.name.ilike(f"%{search}%"))
    vendors = query.order_by(Vendor.name).all()
    return render_template('vendor_center.html', vendors=vendors, search=search)

print("Loading vendors.py - before vendor_profile route")  # At the top
@vendors_bp.route('/vendors/<int:vendor_id>/profile')
@login_required
def vendor_profile(vendor_id):
    vendor = Vendor.query.get_or_404(vendor_id)
    from flask_login import current_user
    if vendor.tenant_id != current_user.tenant_id:
        return "Unauthorized access", 403
    # Get all purchase orders for this vendor
    from inventory_flask_app.models import PurchaseOrder
    from flask_login import current_user
    purchase_orders = PurchaseOrder.query.filter_by(
        vendor_id=vendor.id,
        tenant_id=current_user.tenant_id
    ).order_by(PurchaseOrder.created_at.desc()).all()

    po_list = []
    po_details_map = {}

    for po in purchase_orders:
        units_list = []
        for inst in getattr(po, "instances", []):
            product = inst.product
            units_list.append({
                "serial": inst.serial if inst else "",
                "asset": inst.asset if inst else "",
                "item_name": product.item_name if product else "",
                "make": product.make if product else "",
                "model": product.model if product else "",
                "display": product.display if product else "",
                "cpu": product.cpu if product else "",
                "ram": product.ram if product else "",
                "gpu1": product.gpu1 if product else "",
                "gpu2": product.gpu2 if product else "",
                "grade": product.grade if product else "",
                "disk1size": product.disk1size if product else ""
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
        Product.vendor_id == vendor.id,
        Product.tenant_id == current_user.tenant_id
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
                "serial": inst.serial if inst else "",
                "asset": inst.asset if inst else "",
                "item_name": product.item_name if product else "",
                "make": product.make if product else "",
                "model": product.model if product else "",
                "display": product.display if product else "",
                "cpu": product.cpu if product else "",
                "ram": product.ram if product else "",
                "gpu1": product.gpu1 if product else "",
                "gpu2": product.gpu2 if product else "",
                "grade": product.grade if product else "",
                "disk1size": product.disk1size if product else ""
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
    from flask_login import current_user
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()
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
    from flask_login import current_user
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()
    if vendor.tenant_id != current_user.tenant_id:
        return "Unauthorized access", 403
    from inventory_flask_app.models import PurchaseOrder
    purchase_orders = PurchaseOrder.query.filter_by(
        vendor_id=vendor.id,
        tenant_id=current_user.tenant_id
    ).order_by(PurchaseOrder.created_at.desc()).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Vendor PO History"
    ws.append([
        'PO Number', 'PO Date',
        "serial", "asset", "item_name", "make", "model", "display", "cpu", "ram", "gpu1", "gpu2", "grade", "disk1size"
    ])
    for po in purchase_orders:
        for inst in getattr(po, "instances", []):
            product = inst.product
            ws.append([
                po.po_number or po.id,
                po.created_at.astimezone(get_now_for_tenant().tzinfo).strftime('%Y-%m-%d') if po.created_at else '',
                inst.serial if inst else "",
                inst.asset if inst else "",
                product.item_name if product else "",
                product.make if product else "",
                product.model if product else "",
                product.display if product else "",
                product.cpu if product else "",
                product.ram if product else "",
                product.gpu1 if product else "",
                product.gpu2 if product else "",
                product.grade if product else "",
                product.disk1size if product else ""
            ])
    from inventory_flask_app.models import ProductInstance, Product

    # Get direct-uploaded units (no PO)
    direct_instances = (
        ProductInstance.query
        .join(Product)
        .filter(
            Product.vendor_id == vendor.id,
            Product.tenant_id == current_user.tenant_id,
            ProductInstance.po_id == None
        )
        .all()
    )

    for inst in direct_instances:
        product = inst.product
        ws.append([
            "Direct Upload",  # PO Number
            inst.created_at.strftime('%Y-%m-%d') if inst.created_at else '',  # PO Date
            inst.serial if inst else "",
            inst.asset if inst else "",
            product.item_name if product else "",
            product.make if product else "",
            product.model if product else "",
            product.display if product else "",
            product.cpu if product else "",
            product.ram if product else "",
            product.gpu1 if product else "",
            product.gpu2 if product else "",
            product.grade if product else "",
            product.disk1size if product else ""
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
    from flask_login import current_user
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()
    if vendor.tenant_id != current_user.tenant_id:
        return "Unauthorized access", 403
    upload_date = request.args.get('upload_date')
    if not upload_date:
        return "No upload date specified.", 400

    from inventory_flask_app.models import ProductInstance, Product
    # Find all instances for this vendor and this upload date
    instances = (
        ProductInstance.query
        .join(Product)
        .filter(
            Product.vendor_id == vendor_id,
            Product.tenant_id == current_user.tenant_id,
            db.func.strftime('%Y-%m-%d', db.func.datetime(ProductInstance.created_at, 'localtime')) == upload_date
        )
        .all()
    )
    data = []
    for inst in instances:
        product = inst.product
        data.append({
            "serial": inst.serial if inst else "",
            "asset": inst.asset if inst else "",
            "item_name": product.item_name if product else "",
            "make": product.make if product else "",
            "model": product.model if product else "",
            "display": product.display if product else "",
            "cpu": product.cpu if product else "",
            "ram": product.ram if product else "",
            "gpu1": product.gpu1 if product else "",
            "gpu2": product.gpu2 if product else "",
            "grade": product.grade if product else "",
            "disk1size": product.disk1size if product else ""
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