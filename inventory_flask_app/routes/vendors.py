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
from inventory_flask_app.utils.utils import admin_or_supervisor_required

class VendorForm(FlaskForm):
    name = StringField('Vendor Name', validators=[DataRequired()])
    contact = StringField('Contact', validators=[Optional()])
    email = StringField('Email', validators=[Optional()])
    phone = StringField('Phone', validators=[Optional()])
    address = StringField('Address', validators=[Optional()])

vendors_bp = Blueprint('vendors_bp', __name__)

# --- CSRF Protection ---
# CSRF is set up globally in the app (__init__.py)

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
        def _f(val):
            return val.strip() or None if val else None

        vendor = Vendor(
            name=name,
            contact=contact,
            email=_f(form.email.data),
            phone=_f(form.phone.data),
            address=_f(form.address.data),
            website=_f(request.form.get('website')),
            city=_f(request.form.get('city')),
            country=_f(request.form.get('country')),
            payment_terms=_f(request.form.get('payment_terms')),
            notes=_f(request.form.get('notes')),
            tenant_id=current_user.tenant_id,
        )
        db.session.add(vendor)
        db.session.commit()
        flash(f"✅ Vendor '{name}' added successfully!", 'success')
        next_url = request.args.get('next')
        return redirect(next_url) if next_url else redirect(url_for('vendors_bp.vendor_center'))
    return render_template('add_vendor.html', form=form)


@vendors_bp.route('/vendors/api/search')
@login_required
def api_vendor_search():
    from flask_login import current_user
    from flask import jsonify
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    results = (
        Vendor.query
        .filter(
            Vendor.tenant_id == current_user.tenant_id,
            Vendor.name.ilike(f'%{q}%'),
        )
        .order_by(Vendor.name)
        .limit(10)
        .all()
    )
    return jsonify([
        {'id': v.id, 'name': v.name, 'email': v.email or '', 'phone': v.phone or ''}
        for v in results
    ])


@vendors_bp.route('/vendors/center')
@login_required
def vendor_center():
    from flask_login import current_user
    from sqlalchemy import func, case
    from inventory_flask_app.models import PurchaseOrder, PurchaseOrderItem, ProductInstance, Product

    search   = request.args.get('search', '').strip()
    sort_by  = request.args.get('sort', 'name')    # name | po_count | last_po
    filt     = request.args.get('filter', 'all')   # all | active | no_activity
    page     = request.args.get('page', 1, type=int)
    per_page = 25

    # Fetch all matching vendors (sort in Python after annotation)
    query = Vendor.query.filter_by(tenant_id=current_user.tenant_id)
    if search:
        query = query.filter(
            db.or_(
                Vendor.name.ilike(f'%{search}%'),
                Vendor.email.ilike(f'%{search}%'),
                Vendor.phone.ilike(f'%{search}%'),
                Vendor.city.ilike(f'%{search}%'),
            )
        )
    all_vendors = query.order_by(Vendor.name).all()
    vendor_ids  = [v.id for v in all_vendors]

    # ── PO counts and last PO date ────────────────────────────
    po_stats = {}
    if vendor_ids:
        po_rows = db.session.query(
            PurchaseOrder.vendor_id,
            func.count(PurchaseOrder.id).label('po_count'),
            func.max(PurchaseOrder.created_at).label('last_po'),
        ).filter(
            PurchaseOrder.vendor_id.in_(vendor_ids),
            PurchaseOrder.tenant_id == current_user.tenant_id,
        ).group_by(PurchaseOrder.vendor_id).all()
        po_stats = {r.vendor_id: {'po_count': r.po_count, 'last_po': r.last_po} for r in po_rows}

    # ── Unit counts (replaces vendor.products|length N+1) ─────
    unit_stats = {}
    if vendor_ids:
        unit_rows = db.session.query(
            Product.vendor_id,
            func.count(ProductInstance.id).label('unit_count'),
        ).join(ProductInstance, ProductInstance.product_id == Product.id).filter(
            Product.vendor_id.in_(vendor_ids),
            Product.tenant_id == current_user.tenant_id,
        ).group_by(Product.vendor_id).all()
        unit_stats = {r.vendor_id: r.unit_count for r in unit_rows}

    # ── Fulfillment rates ─────────────────────────────────────
    fulfill_stats = {}
    if vendor_ids:
        f_rows = db.session.query(
            PurchaseOrder.vendor_id,
            func.sum(case(
                (PurchaseOrderItem.status.in_(['received', 'missing']), 1), else_=0
            )).label('expected'),
            func.sum(case(
                (PurchaseOrderItem.status == 'received', 1), else_=0
            )).label('received'),
        ).join(PurchaseOrderItem, PurchaseOrderItem.po_id == PurchaseOrder.id).filter(
            PurchaseOrder.vendor_id.in_(vendor_ids),
            PurchaseOrder.tenant_id == current_user.tenant_id,
        ).group_by(PurchaseOrder.vendor_id).all()
        for r in f_rows:
            exp = r.expected or 0
            rec = r.received or 0
            fulfill_stats[r.vendor_id] = {
                'expected': exp,
                'received': rec,
                'rate': round(rec / exp * 100, 1) if exp > 0 else None,
            }

    # ── Filter ────────────────────────────────────────────────
    if filt == 'active':
        all_vendors = [v for v in all_vendors if po_stats.get(v.id, {}).get('po_count', 0) > 0]
    elif filt == 'no_activity':
        all_vendors = [v for v in all_vendors if not po_stats.get(v.id, {}).get('po_count')]

    # ── Sort in Python ────────────────────────────────────────
    if sort_by == 'po_count':
        all_vendors.sort(key=lambda v: po_stats.get(v.id, {}).get('po_count', 0), reverse=True)
    elif sort_by == 'last_po':
        all_vendors.sort(
            key=lambda v: po_stats.get(v.id, {}).get('last_po') or __import__('datetime').datetime.min,
            reverse=True,
        )
    # 'name' is already sorted from the DB query

    # ── Manual pagination ─────────────────────────────────────
    total       = len(all_vendors)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page        = max(1, min(page, total_pages))
    offset      = (page - 1) * per_page
    vendors     = all_vendors[offset: offset + per_page]

    # Simple pagination object for template
    class _Page:
        def __init__(self):
            self.page       = page
            self.pages      = total_pages
            self.total      = total
            self.has_prev   = page > 1
            self.has_next   = page < total_pages
            self.prev_num   = page - 1
            self.next_num   = page + 1
        def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
            last = 0
            for num in range(1, total_pages + 1):
                if (num <= left_edge or
                    (page - left_current - 1 < num < page + right_current) or
                        num > total_pages - right_edge):
                    if last + 1 != num:
                        yield None
                    yield num
                    last = num

    paginated = _Page()

    return render_template(
        'vendor_center.html',
        vendors=vendors,
        paginated=paginated,
        search=search,
        sort_by=sort_by,
        filt=filt,
        po_stats=po_stats,
        unit_stats=unit_stats,
        fulfill_stats=fulfill_stats,
    )

@vendors_bp.route('/vendors/<int:vendor_id>/profile')
@login_required
def vendor_profile(vendor_id):
    from flask_login import current_user
    from inventory_flask_app.models import (
        PurchaseOrder, ProductInstance, Product,
        VendorNote, Part, Expense
    )
    from collections import defaultdict
    from sqlalchemy.orm import selectinload

    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()
    view = request.args.get('view', 'pos')

    # --- Purchase Orders ---
    purchase_orders = PurchaseOrder.query.filter_by(
        vendor_id=vendor.id,
        tenant_id=current_user.tenant_id
    ).options(
        selectinload(PurchaseOrder.instances).selectinload(ProductInstance.product)
    ).order_by(PurchaseOrder.created_at.desc()).all()

    po_list = []
    po_details_map = {}
    total_units_received = 0

    for po in purchase_orders:
        units_list = []
        for inst in getattr(po, "instances", []):
            product = inst.product
            units_list.append({
                "serial":    inst.serial       if inst    else "",
                "asset":     inst.asset        if inst    else "",
                "status":    inst.status       if inst    else "",
                "item_name": product.item_name if product else "",
                "make":      product.make      if product else "",
                "model":     product.model     if product else "",
                "display":   product.display   if product else "",
                "cpu":       product.cpu       if product else "",
                "ram":       product.ram       if product else "",
                "gpu1":      product.gpu1      if product else "",
                "gpu2":      product.gpu2      if product else "",
                "grade":     product.grade     if product else "",
                "disk1size": product.disk1size if product else "",
            })
        total_units_received += len(units_list)
        po_list.append({
            "po_id": po.id,
            "po_number": po.po_number or po.id,
            "date": po.created_at,
            "total_units": len(units_list),
            "status": po.status or "pending",
        })
        po_details_map[po.id] = units_list

    # --- Direct Uploads (No PO) ---
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
                "serial":    inst.serial       if inst    else "",
                "asset":     inst.asset        if inst    else "",
                "status":    inst.status       if inst    else "",
                "item_name": product.item_name if product else "",
                "make":      product.make      if product else "",
                "model":     product.model     if product else "",
                "display":   product.display   if product else "",
                "cpu":       product.cpu       if product else "",
                "ram":       product.ram       if product else "",
                "gpu1":      product.gpu1      if product else "",
                "gpu2":      product.gpu2      if product else "",
                "grade":     product.grade     if product else "",
                "disk1size": product.disk1size if product else "",
            })
        direct_uploads_list.append({
            "upload_date": date_key,
            "total_units": len(units_list),
            "units": units_list,
        })
        direct_uploads_map[date_key] = units_list

    # --- Parts Supplied ---
    parts_list = Part.query.filter_by(
        vendor_id=vendor.id,
        tenant_id=current_user.tenant_id
    ).order_by(Part.name).all()

    # --- Expenses ---
    expenses_list = Expense.query.filter_by(
        vendor_id=vendor.id,
        tenant_id=current_user.tenant_id,
        deleted_at=None
    ).order_by(Expense.expense_date.desc()).all()
    total_expenses = sum(float(e.amount) for e in expenses_list)

    # --- Notes ---
    notes_list = VendorNote.query.filter_by(
        vendor_id=vendor.id,
        tenant_id=current_user.tenant_id
    ).order_by(VendorNote.created_at.desc()).all()

    # --- Fulfillment metrics from PurchaseOrderItem ---
    from sqlalchemy import func, case
    from inventory_flask_app.models import PurchaseOrderItem
    all_po_ids = [po.id for po in purchase_orders]
    fulfillment = {'expected': 0, 'received': 0, 'missing': 0, 'extra': 0, 'rate': None}
    if all_po_ids:
        f_rows = db.session.query(
            PurchaseOrderItem.status,
            func.count(PurchaseOrderItem.id).label('cnt'),
        ).filter(
            PurchaseOrderItem.po_id.in_(all_po_ids),
            PurchaseOrderItem.tenant_id == current_user.tenant_id,
        ).group_by(PurchaseOrderItem.status).all()
        poi_map = {r.status: r.cnt for r in f_rows}
        expected = poi_map.get('received', 0) + poi_map.get('missing', 0)
        received = poi_map.get('received', 0)
        fulfillment = {
            'expected': expected,
            'received': received,
            'missing':  poi_map.get('missing', 0),
            'extra':    poi_map.get('extra', 0),
            'rate':     round(received / expected * 100, 1) if expected > 0 else None,
        }

    # --- Stats ---
    first_po = purchase_orders[-1].created_at if purchase_orders else None
    last_po = purchase_orders[0].created_at if purchase_orders else None
    stats = {
        "total_pos": len(purchase_orders),
        "total_units": total_units_received,
        "total_parts": len(parts_list),
        "total_expenses": total_expenses,
        "first_po": first_po,
        "last_po": last_po,
        "fulfillment": fulfillment,
    }

    return render_template(
        'vendor_profile.html',
        vendor=vendor,
        view=view,
        po_list=po_list,
        po_details_map=po_details_map,
        direct_uploads_list=direct_uploads_list,
        direct_uploads_map=direct_uploads_map,
        parts_list=parts_list,
        expenses_list=expenses_list,
        notes_list=notes_list,
        stats=stats,
    )


@vendors_bp.route('/vendors/<int:vendor_id>/notes/add', methods=['POST'])
@login_required
def add_vendor_note(vendor_id):
    from flask_login import current_user
    from inventory_flask_app.models import VendorNote
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()
    note_text = request.form.get('note', '').strip()
    if note_text:
        note = VendorNote(
            tenant_id=current_user.tenant_id,
            vendor_id=vendor.id,
            note=note_text,
            created_by=current_user.id,
        )
        db.session.add(note)
        db.session.commit()
        flash('Note added.', 'success')
    return redirect(url_for('vendors_bp.vendor_profile', vendor_id=vendor.id, view='notes'))


@vendors_bp.route('/vendors/<int:vendor_id>/notes/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_vendor_note(vendor_id, note_id):
    from flask_login import current_user
    from inventory_flask_app.models import VendorNote
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()
    note = VendorNote.query.filter_by(id=note_id, vendor_id=vendor.id, tenant_id=current_user.tenant_id).first_or_404()
    db.session.delete(note)
    db.session.commit()
    flash('Note deleted.', 'success')
    return redirect(url_for('vendors_bp.vendor_profile', vendor_id=vendor.id, view='notes'))


# Add edit_vendor route
@vendors_bp.route('/vendors/<int:vendor_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_vendor(vendor_id):
    from flask_login import current_user
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()
    def _f(key):
        v = request.form.get(key, '').strip()
        return v or None

    if request.method == 'POST':
        vendor.name          = request.form.get('name', '').strip()
        vendor.contact       = _f('contact')
        vendor.email         = _f('email')
        vendor.phone         = _f('phone')
        vendor.address       = _f('address')
        vendor.website       = _f('website')
        vendor.city          = _f('city')
        vendor.country       = _f('country')
        vendor.payment_terms = _f('payment_terms')
        vendor.notes         = _f('notes')
        db.session.commit()
        flash('Vendor updated successfully!', 'success')
        return redirect(url_for('vendors_bp.vendor_profile', vendor_id=vendor.id))
    return render_template('edit_vendor.html', vendor=vendor)


@vendors_bp.route('/vendors/<int:vendor_id>/delete', methods=['POST'])
@login_required
@admin_or_supervisor_required
def delete_vendor(vendor_id):
    from flask_login import current_user
    from inventory_flask_app.models import PurchaseOrder, Part
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()

    has_pos   = PurchaseOrder.query.filter_by(vendor_id=vendor.id).first()
    has_parts = Part.query.filter_by(vendor_id=vendor.id).first()

    if has_pos or has_parts:
        flash('Cannot delete a vendor with purchase orders or linked parts.', 'danger')
        return redirect(url_for('vendors_bp.edit_vendor', vendor_id=vendor.id))

    db.session.delete(vendor)
    db.session.commit()
    flash('Vendor deleted.', 'success')
    return redirect(url_for('vendors_bp.vendor_center'))

from openpyxl import Workbook
from io import BytesIO

@vendors_bp.route('/vendors/<int:vendor_id>/export_po')
@login_required
def export_vendor_po(vendor_id):
    from flask_login import current_user
    vendor = Vendor.query.filter_by(id=vendor_id, tenant_id=current_user.tenant_id).first_or_404()
    from inventory_flask_app.models import PurchaseOrder
    purchase_orders = PurchaseOrder.query.filter_by(
        vendor_id=vendor.id,
        tenant_id=current_user.tenant_id
    ).order_by(PurchaseOrder.created_at.desc()).all()
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

    if not purchase_orders and not direct_instances:
        flash("⚠️ No purchase orders or uploaded units found for this vendor.", "warning")
        return redirect(url_for('vendors_bp.vendor_profile', vendor_id=vendor.id))

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
                po.created_at.strftime('%Y-%m-%d') if po.created_at else '',
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
            db.func.date(ProductInstance.created_at) == upload_date
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
